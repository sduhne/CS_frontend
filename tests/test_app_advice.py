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
        # two places from the money the chart folds; the default style follows it for a thin edge: with 12bb
        # at risk that is under +0.24bb (A3), and A7o is worth +0.09bb here
        a = A.advise(tournament(STACKS_A, BTN, "A7o", left=152))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("only up to 8.5bb this close to the money (17bb far from it)", a["reason"])
        # A8o is worth +0.20bb: the line for 10bb at risk, but thin for 12bb
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("A thin edge (+0.20bb, where 12bb at risk takes +0.24bb)", a["reason"])
        # A7s is worth +0.32bb: a clear edge, played
        a = A.advise(tournament(STACKS_A, BTN, "A7s", left=152))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.32bb, needs +0.24bb)", a["source"])
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152, style="maxev"))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "off"))
        self.assertEqual(a["tiles"][0]["value"], "+0.20bb")

    def test_T6_close_to_the_money_reads_twice_the_stack(self):
        # the table at 24bb folds A5o (an all-in up to 15bb).  The strict guard of "Cash first" follows it ...
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("up to 7.5bb this close to the money (15bb far from it)", a["reason"])   # in his own chips (A2)
        self.assertIn("ALL-IN +0.44bb", a["also"])
        # ... the default style only when the engine's edge is thin, and +0.55bb is not (PRE-7)
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.55bb, needs +0.24bb): played although the all-in table folds", a["source"])

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
        # 46% where the call takes 33% (the price plus the points for play after the flop), and a hand the
        # sheet calls: the engine's "close" is not repeated beside those two numbers (A5, C6)
        self.assertEqual(a["headline"]["sure"], "standard")
        self.assertEqual(a["tiles"][0]["value"], "33% / 46%")
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
        # The button with 12bb against all-ins of 40 and 22bb can win 12bb from each: the price is 43%, not the
        # 28% of the whole of both stacks, and the engine itself folds tens (39%).
        a = A.advise(tournament(STACKS_A, BTN, "TT", acts=two, left=185))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "none"))
        self.assertEqual(a["tiles"][0]["value"], "43% / 39%")
        # the button covers both (40bb against 14 and 12bb): the engine calls, and the guard has its say
        covers = [30, 25, 18, 14, 12, 40, 15, 20]
        a = A.advise(tournament(covers, BTN, "TT", acts=two, left=185, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("CALL", a["also"])
        a = A.advise(tournament(covers, BTN, "QQ", acts=two, left=185))         # 13 points over: no thin edge
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
        # a close call in the big blind: fit-or-fold, "Close: ...", prizes estimated, bounties (Q4s has 32% where
        # the call takes 26%; K9o against a button raise is no longer "close", A5)
        s = tournament([12] * 8, BB, "Q4s", acts=[(UTG, "raise", 2)])
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
        self.assertEqual(verb(a), "ALL-IN")                 # A9o from the button is an all-in up to 24bb: 12bb here
        self.assertIn("up to 12bb this close to the money (24bb far from it)", a["reason"])
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
        # A3: one bar far from the money and close to it, growing with the big blinds at risk
        self.assertEqual((A.THIN_EV_BB, A.THIN_EV_PER_BB, A.THIN_EV_FROM_BB), (0.20, 0.02, 10))
        self.assertEqual((A.THIN_EDGE_POINTS_FAR, A.THIN_EDGE_POINTS_CLOSE), (4, 7))
        # the measure itself: an all-in by the engine's "all-in against folding", a call by have minus need,
        # and a play without a number counts as thin
        for near in (False, True):
            self.assertEqual(A.engine_edge(A.Play("ALL-IN", "allin", facts={"ev": 0.20}), near, 10),
                             (False, "engine +0.20bb", "+0.20bb"))
            self.assertEqual(A.engine_edge(A.Play("ALL-IN", "allin", facts={"ev": 0.19}), near, 10),
                             (True, "engine +0.19bb", "+0.20bb"))
        call = A.Play("CALL", "call", facts={"need": 0.47, "equity": 0.53, "ev": 2.0})
        self.assertEqual(A.engine_edge(call, near=False, at_risk_bb=30), (False, "53% against 47%", ""))
        self.assertEqual(A.engine_edge(call, near=True, at_risk_bb=30), (True, "53% against 47%", ""))
        self.assertEqual(A.engine_edge(A.Play("RE-RAISE", "raise"), near=False), (True, "", ""))
        # thin and the table folds: the survival fold, in both styles (K9s in the cutoff, +0.15bb)
        for style in (None, "cash"):
            a = A.advise(tournament(STACKS_B, CO, "K9s", style=style))
            self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"), style)
        thin = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertIn("A thin edge (+0.15bb, where 14bb at risk takes +0.28bb)", thin["reason"])
        self.assertIn("with a clear edge", thin["flip"])
        # a clear edge far from the money: A8o on the button with 12bb at 300 left was a survival fold (+1.06bb)
        clear = A.advise(tournament(STACKS_A, BTN, "A8o", left=300))
        self.assertEqual(verb(clear), "ALL-IN")
        self.assertIn(clear["guard"], ("edge", "agrees"))

    def test_pre_7_seventeen_big_blinds_or_more_the_sheets_small_raise_not_a_fold(self):
        # 22 on the button with 18bb in "Cash first": the engine moves all-in for +0.35bb, the chart folds (22 is
        # an all-in up to 15bb there), and the sheet raises 22 from the button: the headline is that raise, with
        # the plan against an all-in.  (The default style as well, since A3: 18bb at risk takes +0.36bb.)
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
        # the default style makes the same raise since the thin edge grows with the stack at risk (A3): 44 in
        # the cutoff with 18bb is worth +0.26bb as an all-in, and 18bb at risk takes +0.36bb
        default = A.advise(tournament([18] * 8, CO, "44"))
        self.assertEqual((verb(default), default["guard"]), ("RAISE", "survival"))
        self.assertIn("SURVIVAL RAISE (engine: ALL-IN +0.26bb): the sheet's small raise", default["source"])
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
            # (K2o is on the sheet's row against a button raise, "call as well: K2o, ...", and not on the short
            # list; Q3o is on neither: the reason says which of the two it is)
            deep = A.advise(tournament([30] * 8, BB, "K2o", acts=small_raise))
            self.assertEqual((verb(deep), deep["guard"]), ("FOLD", "close"))
            self.assertIn("not a hand that makes top pair or a real draw", deep["reason"])
            deep = A.advise(tournament([30] * 8, BB, "Q3o", acts=small_raise))
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
        self.assertLess(took, 3.0, "12 seconds by the integral; about 0.2 s in closed form")
        exact, large = self.models(s)
        # A4: nothing is merged any more.  The same ladder, the same field, valued in closed form
        self.assertTrue(large.large)
        self.assertFalse(exact.large)
        self.assertEqual(len(large.raw_payouts), 22000)
        self.assertEqual((large.field_n, large.field_stack, large.itm_bonus),
                         (exact.field_n, exact.field_stack, exact.itm_bonus))
        # the stage, the fold clock and the source line still read the real numbers
        self.assertIn("ICM", a["source"])
        self.assertEqual(A.read_money(s).stage["remaining"], 30000)
        self.assertTrue(A.read_money(s).field_prizes.large)         # the opponents are priced by the same model

    def test_l6_a_5_000_entrant_field_is_not_touched(self):
        for left in (1200, 800, 755, 700, 40):
            exact, thin = self.models(self.field(5000, left, 750))
            self.assertIs(thin, exact, left)                       # 750 paid places: under the cap, the same object
        # and late in a huge field, with fewer players left than the cap, it is the exact ladder again
        exact, thin = self.models(self.field(150000, 900, 22000))
        self.assertIs(thin, exact)
        self.assertGreater(A.PRIZE_PLACES, 750)

    def test_l6_the_large_field_model_keeps_the_money_line_and_the_prizes(self):
        # (was: the thinned ladder.)  Before the money a player who busts now gets nothing; in the money he
        # gets the prize of his real place, and the model's prizes are the real ladder's, place by place.
        from poker_coach.icm import hero_equity, large_field_equity
        for left in (30000, 22100, 22003, 22001, 22000, 21000, 5000):
            exact, large = self.models(self.field(150000, left, 22000))
            self.assertEqual(large.raw_payouts, exact.raw_payouts, left)
            chips = [0.0] + [20000.0 * 600 / 600] * 7           # hero has no chips: he is out, behind everybody
            busts = large.value(chips, 0)
            want = exact.payouts[left - 1] if left <= 22000 else 0.0
            self.assertAlmostEqual(busts, want, places=9, msg=left)
        # value by value the closed form is the integral (here on a field the integral still does quickly)
        pays = exact.raw_payouts[:3000]
        for stacks, field_n in (([6000.0, 240000.0, 90000.0], 3001), ([360000.0] + [12000.0] * 8, 2994),
                                ([30000.0, 30000.0], 4500)):
            for who in (0, 1):
                want = hero_equity(stacks, who, pays, field_n, 240000.0)
                got = large_field_equity(stacks, who, pays, field_n, 240000.0)
                self.assertAlmostEqual(got / want, 1.0, delta=0.002, msg=(stacks, field_n, who))

    def test_l6_the_large_field_model_prices_risk_like_the_exact_one(self):
        # 20,000 entrants and 3,000 paid, stacks around the average: far from the money, near it, on the
        # bubble and in the money.  The risk premium (points of equity) is the number the answers are made of.
        # (The thinned model was allowed 0.3 to 1.5 points here; the closed form is within a twentieth.)
        stacks = [10, 60, 33, 33, 20, 45, 15, 80]
        for left, styles in ((4000, (None,)), (3010, (None, "cash")), (3001, ("cash",)), (2900, (None,))):
            bb = max(100, int(20000 * 20000 / left / 30 / 100) * 100)
            for style in styles:
                exact, large = self.models(self.field(20000, left, 3000, bb=bb, stacks=stacks, style=style, cards=""))
                self.assertIsNot(large, exact)
                chips = [float(x * bb) for x in stacks]
                for hero, villain in ((0, 1), (1, 0), (3, 7)):
                    want, got = exact.risk_premium(chips, hero, villain), large.risk_premium(chips, hero, villain)
                    self.assertAlmostEqual(100 * got, 100 * want, delta=0.05, msg=(left, style, hero, villain))


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
        self.assertEqual(strict["reason"], "Fold before the money: A5o from the button is an all-in only up to 7.5bb "
                                           "this close to the money (15bb far from it).")
        thin = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertEqual(thin["reason"], "A thin edge (+0.15bb, where 14bb at risk takes +0.28bb): fold before the "
                                         "money. K9s from the cutoff is an all-in only up to 8bb.")
        small = A.advise(tournament([18] * 8, BTN, "22", style="cash"))
        self.assertEqual(small["reason"], "No all-in before the money: 22 from the button is an all-in only up to "
                                          "15bb. The sheet raises this hand small from this seat instead: raise, "
                                          "and fold to an all-in.")
        for answer in (strict, thin, small):
            self.assertNotIn("((", answer["reason"])
            self.assertNotIn("BTN", answer["reason"])
        # the all-in plan reads the same chart in the same words
        plan = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, plan="allin"))
        self.assertEqual(plan["reason"], "A5o from the button is an all-in only up to 7.5bb this close to the money "
                                         "(15bb far from it).")
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

    def test_a_fold_from_the_opening_chart_shows_no_all_in_gain_beside_it(self):
        # the small blind with 22bb and A2o: outside the opening range, FOLD, while the engine's reference
        # number for an all-in is +0.70bb.  A green "all-in against folding" beside the fold says "all-in".
        a = A.advise(tournament([22] * 8, SB, "A2o"))
        self.assertEqual((verb(a), a["headline"]["sure"]), ("FOLD", "close"))
        self.assertNotIn("All-in against folding", [t["label"] for t in a["tiles"]])
        self.assertNotIn("Everybody folds", [t["label"] for t in a["tiles"]])
        close = next(w["text"] for w in a["warnings"] if w["code"] == "close")
        self.assertNotIn("all-in earns", close)
        # where the solver decides (16bb and under) the number stays beside the answer it made
        a = A.advise(tournament([12] * 8, SB, "72o"))
        self.assertEqual(verb(a), "FOLD")
        self.assertIn("All-in against folding", [t["label"] for t in a["tiles"]])

    def test_a_close_all_in_in_place_of_a_small_re_raise_names_its_own_bar(self):
        # in the money, tens on the button against a cutoff raise with 30bb: the all-in earns +1.36bb, and it is
        # "close" to the call it replaces (the bar is 4% of the stack), not to the +0.15bb of a short all-in
        a = A.advise(tournament([30] * 8, BTN, "TT", acts=[(CO, "raise", 2.2)], left=100))
        self.assertEqual((verb(a), a["headline"]["sure"]), ("ALL-IN", "close"))
        close = next(w["text"] for w in a["warnings"] if w["code"] == "close")
        self.assertIn("in place of a small re-raise it takes +1.20bb", close)
        self.assertNotIn("+0.15bb", close)

    def test_the_sit_out_line_is_not_given_as_thousands_of_percent(self):
        a = A.advise(tournament([69, 30], 0, "5s3d", left=151, avg_bb=25))
        clock = a["context"]["fold_clock"]
        self.assertIn("You hold 15 times what it takes to fold into the money (the sit-out line).", clock)
        self.assertFalse(re.search(r"\d{3,}%", clock), clock)
        a = A.advise(tournament([30, 25, 18, 40, 22, 8, 15, 20], BTN, "A9o", left=165, avg_bb=30, plan="allin"))
        self.assertIn("You hold 31% of what it takes to fold into the money (the sit-out line).",
                      a["context"]["fold_clock"])
        # the all-in plan's own sentence on the bubble says it the same way
        self.assertEqual(A.of_the_line(8.72), "8.7 times the sit-out line")     # (was "872%", then "9 times")
        self.assertEqual(A.of_the_line(25.24), "25 times the sit-out line")
        self.assertEqual(A.of_the_line(0.31), "31% of the sit-out line")
        A.warm_bubble_charts(8)
        a = A.advise(tournament([20] * 7 + [60], BB, "7h2d", acts=[(BTN, "allin", None)], left=151, avg_bb=10,
                                plan="allin"))
        self.assertIn("times the sit-out line you fold into the money", a["reason"])
        self.assertFalse(re.search(r"\d{3,}%", a["reason"]), a["reason"])

    def test_the_all_in_plan_never_folds_a_cheap_call_at_a_good_price(self):
        # the big blind with 23bb, an all-in of 1.3bb in front: 205 more into a pot of 3,700.  The chart
        # reads the size of the all-in and folded 6-4 suited at 18 to 1.
        stacks = [40] * 8
        stacks[BB], stacks[UTG1] = 23.4, 1.33
        a = A.advise(tournament(stacks, BB, "64s", acts=[(UTG1, "allin", None)], left=100, plan="allin"))
        self.assertEqual((verb(a), a["headline"]["follow"]), ("CALL", {"kind": "call"}))
        self.assertIn("a good price is never folded", source(a))
        self.assertIn("a price like this is never folded", a["reason"])
        self.assertNotRegex(a["reason"], r"\d\.\d{2,}bb")             # "an all-in of 1.3bb", not 1.32833bb
        # on the bubble with the stack over the sit-out line: kings are not folded for a ninth of the stack
        a = A.advise(tournament([1.9, 7.8], 1, "KhKd", acts=[(0, "allin", None)], left=151, plan="allin"))
        self.assertEqual(verb(a), "CALL")
        # a call for a third of the stack or more stays the chart's: T8s with 6bb against a 3bb all-in
        stacks = [20] * 8
        stacks[BB], stacks[BTN] = 6, 3
        a = A.advise(tournament(stacks, BB, "T8s", acts=[(BTN, "allin", None)], plan="allin"))
        self.assertEqual(source(a).split(" \u00b7 ")[-1], "all-in or fold table")

    def test_a_fold_made_by_a_rule_shows_no_all_in_gain_beside_it(self):
        # a raise and a re-raise in front, hero deep with A8o: "fold everything except the very top", while the
        # engine's reference number for a 75bb all-in can be a gain.  The tile would say "all-in".
        with engine_says("FOLD", "clear", why=["a raise and a re-raise in front: fold everything except the very "
                                               "top of your range"],
                         numbers=["3-bettor's range ~3.0% [KK+]; your equity 30%",
                                  "shove EV +0.66bb vs folding; both fold 83%; when called you have 25%"]):
            a = A.advise(tournament([75] * 8, HJ, "A8o", acts=[(UTG1, "raise", 2.2), (LJ, "raise", 6.6)]))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual([t["label"] for t in a["tiles"]], ["Their range"])
        # a fold the number backs keeps it: the solver decides there
        with engine_says("FOLD", "standard", numbers=["re-shove EV +0.08bb vs folding (chip EV); everyone folds 60%; "
                                                      "when called you have 40%"]):
            a = A.advise(tournament([20] * 8, BTN, "KQo", acts=[(CO, "raise", 2)]))
        self.assertIn("All-in against folding", [t["label"] for t in a["tiles"]])


# --------------------------------------------------------------------------
# The close-out round: one test for each item (A2 to A5)
# --------------------------------------------------------------------------

class CloseOut(unittest.TestCase):

    def test_a1_the_all_in_plan_calls_a_good_price_only_against_an_all_in(self):
        # Found by the sweep of every hand in one spot: in the all-in plan the big blind against a button raise
        # called K9o and K8s "at a good price" and folded K9s and KTo, which the full engine moves all-in with
        # and the chart folds.  The plan never just calls a raise: all four fold.
        raised = [(BTN, "raise", 2)]
        for hand in ("K9s", "KTo", "K9o", "K8s"):
            a = A.advise(tournament([12] * 8, BB, hand, acts=raised, plan="allin"))
            self.assertEqual(verb(a), "FOLD", hand)
        # ... and on the bubble with the stack over the sit-out line nines do not call where aces sit out
        A.warm_bubble_charts(8)
        for hand in ("AA", "99"):
            a = A.advise(tournament([40] * 8, BB, hand, acts=[(BTN, "raise", 2.2)], left=160, plan="allin"))
            self.assertEqual(verb(a), "FOLD", hand)
        # Against a real all-in the price still counts, for every hand the full engine plays: the small blind
        # with K7o, which the engine raises over a 1.3bb all-in, calls it as the big blind does with 6-4 suited.
        stacks = [40] * 8
        stacks[UTG1] = 1.3
        tiny = [(UTG1, "allin", None)]
        a = A.advise(tournament(stacks, SB, "K7o", acts=tiny, plan="allin"))
        self.assertTrue(a["also"].startswith("With all moves, on these stacks: RE-RAISE"), a["also"])
        self.assertEqual(verb(a), "CALL")
        self.assertIn("a good price is never folded", a["source"])
        a = A.advise(tournament(stacks, BB, "64s", acts=tiny, plan="allin"))
        self.assertEqual(verb(a), "CALL")
        # (seen on the way: in this plan a small gain beside two folds, the chart's and the engine's, says the
        # line it is under, as it does with all moves)
        a = A.advise(tournament([12] * 8, BTN, "A8o", acts=[(HJ, "call", None)], left=260, plan="allin"))
        gain = next(t for t in a["tiles"] if t["label"] == "All-in against folding")
        self.assertEqual((verb(a), a["also"]), ("FOLD", "With all moves, on these stacks: FOLD."))
        self.assertEqual((gain["sign"], gain["note"]), (1, "with all moves, under the +0.15bb it takes over callers"))

    def test_a2_close_to_the_money_the_chart_limit_is_said_in_hero_s_own_chips(self):
        # The button with A8o and 12.4bb, 96 left, 75 paid.  This close to the money the chart is read at twice
        # the stack (24.8bb) and folds a hand it moves in with "up to 21bb": beside a stack of 12.4bb that read
        # as a contradiction.  Every place now gives the limit in his chips: 10.5bb.
        stacks = [30, 25, 18, 40, 22, 12.4, 15, 20]
        a = A.advise(tournament(stacks, BTN, "A8o", left=96, paid=75))
        self.assertEqual(a["tiles"][-1], {"label": "The chart says", "value": "FOLD",
                                          "note": "all-in up to 10.5bb this close to the money", "sign": 0})
        self.assertEqual(a["flip"], "The all-in chart moves in with A8o up to 10.5bb from this seat this close to "
                                    "the money (21bb far from it).")
        strict = A.advise(tournament(stacks, BTN, "A8o", left=96, paid=75, style="cash"))
        self.assertEqual(strict["reason"], "Fold before the money: A8o from the button is an all-in only up to "
                                           "10.5bb this close to the money (21bb far from it).")
        self.assertEqual(strict["tiles"][-1]["note"], "all-in up to 10.5bb this close to the money")
        # the chart's title names the column and says whose stack it is twice of; its cells are in his chips
        chart = strict["chart"]
        self.assertEqual(chart["title"], "All-in chart: button, first in, 24.8bb (twice your 12.4bb)")
        row, column = divmod(HANDS.index("A8o"), 13)
        self.assertEqual(chart["numbers"][row][column], "all-in up to 10.5bb this close to the money")
        # (the all-in plan a little further out: on the bubble itself it reads the bubble charts)
        plan = A.advise(tournament(stacks, BTN, "A8o", left=130, paid=75, plan="allin"))
        self.assertEqual(plan["reason"], "A8o from the button is an all-in only up to 10.5bb this close to the money "
                                         "(21bb far from it).")
        self.assertEqual(plan["tiles"][0], {"label": "The chart", "value": "all-in up to 10.5bb",
                                            "note": "A8o from this seat, this close to the money", "sign": 0})
        # no sentence, tile or title of the three answers names 21bb without saying where it holds
        for answer in (a, strict, plan):
            texts = [answer["reason"], answer["flip"], answer["also"], (answer["chart"] or {}).get("title", "")]
            texts += [f"{t['value']} {t['note']}" for t in answer["tiles"]]
            for text in texts:
                self.assertFalse("21bb" in text and "21bb far from it" not in text, text)
        # far from the money nothing changes: the chart's number is the stack he holds
        far = A.advise(tournament(stacks, BTN, "A8o"))
        self.assertIn("up to 21bb from this seat before the money", far["flip"])
        # over a raise the doubled row is announced before a stack he does not hold is named
        over = A.advise(tournament([15] * 8, BTN, "99", acts=[(CO, "raise", 2)], left=260, plan="allin"))
        self.assertEqual(over["reason"], "This close to the money your 15bb counts double, and over a raise from CO "
                                         "with 25 to 40bb the chart moves all-in with 99+, AQs+, AKo.")
        self.assertEqual(over["chart"]["title"], "All-in chart: over a raise from CO, 30bb (twice your 15bb)")
        # deeper than the chart goes only aces and kings move in: the tile says that, not "never an all-in"
        deep = A.advise(tournament([45] * 8, BTN, "AA", plan="allin"))
        self.assertEqual((verb(deep), deep["tiles"][0]["value"]), ("ALL-IN", "over 40bb: AA, KK only"))
        deep = A.advise(tournament([25] * 8, BTN, "AA", left=260, plan="allin"))
        self.assertEqual(deep["tiles"][0]["value"], "over 20bb: AA, KK only")
        self.assertEqual(deep["tiles"][0]["note"], "AA from this seat, this close to the money")
        self.assertEqual(deep["chart"]["title"], "All-in chart: button, first in, 50bb (twice your 25bb)")
        # half a big blind over a limit still reads as the limit, and the sentence says so
        self.assertEqual(A.counts_as(21.4, 21, False), "your 21.4bb counts as 21bb")
        self.assertEqual(A.counts_as(10.7, 21, True), "your 10.7bb counts as 10.5bb")
        self.assertEqual(A.counts_as(10.5, 21, True), "")
        # the guard reads a doubled stack from the deepest column at most: a hand of that column has no limit
        self.assertEqual(A.own_limit(40, True, capped=True), 40.0)
        self.assertEqual(A.limit_words(40, True, capped=True), "up to 40bb this close to the money")
        self.assertEqual(A.limit_words(28, True), "up to 14bb this close to the money (28bb far from it)")

    def test_a3_the_thin_edge_grows_with_the_stack_at_risk(self):
        # the bar: 0.20bb up to 10bb at risk, then 0.02bb more for every big blind (the all-in charts' own margin)
        self.assertEqual([A.thin_bar(bb) for bb in (6, 10, 12, 21, 30)], [0.20, 0.20, 0.24, 0.42, 0.60])
        # King-jack suited in the big blind, 21bb, 21 places from the money, against a raise from the lojack:
        # the all-in is worth +0.35bb.  Under the flat 0.20bb that was "CLEAR EDGE"; for 21bb at risk it is thin,
        # and the quieter play the sheet allows leads (the big blind's call).
        a = A.advise(tournament([21] * 8, BB, "KJs", acts=[(LJ, "raise", 2)], left=171))
        self.assertEqual((verb(a), a["guard"], a["headline"]["sure"]), ("CALL", "survival", "standard"))
        self.assertTrue(a["reason"].startswith("A thin edge (+0.35bb, where 21bb at risk takes +0.42bb): no all-in "
                                               "before the money."), a["reason"])
        self.assertIn("SURVIVAL CALL (engine: ALL-IN +0.35bb)", a["source"])
        # against the cutoff's wider raise it is worth +0.50bb: over the bar, and the source line names the bar
        a = A.advise(tournament([21] * 8, BB, "KJs", acts=[(CO, "raise", 2)], left=171))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "edge"))
        self.assertIn("CLEAR EDGE (engine +0.50bb, needs +0.42bb): played although the all-in table folds", a["source"])
        # with 17bb or more the survival fold of an all-in is the sheet's small raise again in the default
        # style: 44 in the cutoff with 18bb (+0.26bb, and 18bb at risk takes +0.36bb)
        a = A.advise(tournament([18] * 8, CO, "44"))
        self.assertEqual((verb(a), a["guard"], a["headline"]["qualifier"]), ("RAISE", "survival", "survival raise"))
        self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 2000})
        self.assertTrue(a["reason"].startswith("A thin edge (+0.26bb, where 18bb at risk takes +0.36bb): no all-in "
                                               "before the money."), a["reason"])
        self.assertTrue(a["plans"] and all(line.startswith("If ") for line in a["plans"]), a["plans"])
        # A play the engine itself marks close is never shown as a clear edge, however big its number: it is
        # close to the engine's own line for that all-in, and the reason says so.
        with engine_says("ALL-IN", "close", why=["a small re-raise would have to fold to an all-in with this hand: "
                                                 "move all-in now, it earns"],
                         numbers=["re-shove EV +1.38bb vs folding (ICM); everyone folds 70%; when called you have 40%"],
                         data={"reshove_ev_bb": 1.38, "reshove_bar_bb": 1.11}):
            a = A.advise(tournament([28] * 8, BB, "AJs", acts=[(CO, "raise", 2.2)]))
        self.assertEqual((a["guard"], a["headline"]["sure"]), ("survival", "standard"))
        self.assertNotIn("CLEAR EDGE", a["source"])
        self.assertTrue(a["reason"].startswith("Close by the numbers (+1.38bb against folding, just over the +1.11bb "
                                               "it takes in place of a small re-raise): no all-in"), a["reason"])
        self.assertNotIn("thin edge", a["reason"])
        # ... and the pill never contradicts the source line: every hand of one spot two places from the money
        s = tournament(STACKS_A, BTN, "AA", left=152)
        seen = set()
        for hand in HANDS:
            s.do("set_cards", hero=hand, replace=True)
            a = A.advise(s)
            sure, src = a["headline"]["sure"], a["source"]
            close_said = any(w["code"] == "close" for w in a["warnings"]) or a["reason"].startswith("Close")
            seen.add(a["guard"])
            with self.subTest(hand=hand):
                if "CLEAR EDGE" in src:
                    self.assertFalse(sure == "close" or close_said or "thin edge" in a["reason"], (sure, src))
                if sure == "clear":
                    self.assertFalse("CLOSE:" in src or close_said or "thin edge" in a["reason"], (sure, src))
                if "thin edge" in a["reason"]:
                    self.assertEqual((a["guard"], sure), ("survival", "standard"))
                self.assertEqual(a["guard"] == "edge", "CLEAR EDGE" in src)
        self.assertTrue({"edge", "survival", "agrees"} <= seen, seen)

    def test_a4_a_short_stack_near_the_money_in_a_very_large_field(self):
        from poker_coach import state as S
        from poker_coach.app.model import goal_for

        def big_field(entrants, left, paid, stacks_bb, avg_bb, style=None, bb=1000):
            s = Session(save=False)
            s.do("new_session", mode="tournament", size=len(stacks_bb), start_stack=20000,
                 level=f"{bb // 2}/{bb}/{bb // 8}", entrants=entrants, remaining=left, paid=paid, button=2)
            s.do("set_stacks", values=[x * bb for x in stacks_bb])
            s.do("set_tournament", avg_stack=avg_bb * bb)
            if style:
                s.do("set_config", style=style)
            state = s.engine_state()
            exact = S.build_prizes(state, goal_for(s.data))
            chips = [float(S.seats(state)[str(seat)]["stack"]) for seat in S.occupied(state)]
            return s, exact, A.thinned_prizes(exact, len(chips)), chips

        # The measured case: 20,000 entrants, 3,003 left, 3,000 paid, a 12bb stack at 5% of the average.  With
        # the field thinned three places from the money became one, and one bust at a table of short stacks
        # filled it: the risk premium read 30 points where the exact model has 17.5.
        tables = {"short": [12] * 9, "mixed": [12, 240, 100, 400, 30, 600, 60, 240, 150]}
        for name, stacks in tables.items():
            for left in (3050, 3010, 3003, 3001, 3000, 2400):
                for style in (None, "cash"):
                    _s, exact, large, chips = big_field(20000, left, 3000, stacks, avg_bb=240, style=style)
                    self.assertTrue(large.large)
                    for villain in (1, 3):
                        want, got = exact.risk_premium(chips, 0, villain), large.risk_premium(chips, 0, villain)
                        with self.subTest(table=name, left=left, style=style, villain=villain):
                            self.assertAlmostEqual(100 * got, 100 * want, delta=0.1)        # (2 points were allowed)
        _s, exact, large, chips = big_field(20000, 3003, 3000, tables["short"], avg_bb=240)
        self.assertAlmostEqual(100 * exact.risk_premium(chips, 0, 1), 17.5, delta=0.3)
        # hero's own stack from 5% to 300% of the average, 3 places from the money
        for share in (0.15, 0.30, 1.0, 3.0):
            stacks = [round(240 * share)] + tables["mixed"][1:]
            _s, exact, large, chips = big_field(20000, 3003, 3000, stacks, avg_bb=240)
            self.assertAlmostEqual(100 * large.risk_premium(chips, 0, 1), 100 * exact.risk_premium(chips, 0, 1),
                                   delta=0.1, msg=share)
        # and an answer for nine players at 150,000 entrants comes well inside a second (the median of five)
        took = []
        for left in (30000, 22050, 22003, 22000, 15000):
            s, _exact, _large, _chips = big_field(150000, left, 22000, [20] * 9, avg_bb=40)
            s.do("deal", hero_cards="AJs")
            started = time.perf_counter()
            a = A.advise(s)
            took.append(time.perf_counter() - started)
            self.assertEqual((a["status"], a["icm"]), ("ready", "on"), left)
        self.assertLess(sorted(took)[2], 1.0, took)
        # a 5,000-entrant field is still the integral: the very same object, so the very same answers
        _s, exact, same, _chips = big_field(5000, 760, 750, [20] * 9, avg_bb=40)
        self.assertIs(same, exact)

    def test_a5_close_is_said_of_two_numbers_that_are_close(self):
        # C6: the big blind against a raise.  The engine's test is the price plus points for play after the
        # flop; the bare pot odds stood beside the word close ("CALL, 40% against 20%").
        a = A.advise(tournament([28] * 8, BB, "K8o", acts=[(CO, "raise", 2.2)]))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "close"))
        self.assertEqual(a["tiles"][0]["label"], "Need / have")
        self.assertEqual(a["tiles"][0]["value"], "35% / 40%")
        self.assertTrue(a["reason"].startswith("Close (40% where the call takes 35%), and not a hand that makes top "
                                               "pair or a real draw"), a["reason"])
        self.assertIn("(engine: CALL, 40% against 35%)", a["source"])
        # eight points to spare are not "close": the hand is folded for what it is
        a = A.advise(tournament([15] * 8, BB, "K5o", acts=[(BTN, "raise", 2)]))
        self.assertEqual((verb(a), a["tiles"][0]["value"]), ("FOLD", "33% / 41%"))
        self.assertTrue(a["reason"].startswith("A call by the price (41% where it takes 33%), but not a hand the "
                                               "sheet calls a small raise with"), a["reason"])
        self.assertNotIn("Close", a["reason"])
        self.assertEqual((a["headline"]["sure"], a["headline"]["qualifier"]), ("standard", "not on the sheet's list"))
        self.assertIn("SHEET FOLD (engine: CALL, 41% against 33%)", a["source"])
        # a call that is kept: close with six points to spare, and the warning says the same two numbers ...
        kept = A.advise(tournament([12] * 8, BB, "Q4s", acts=[(UTG, "raise", 2)]))
        self.assertEqual((verb(kept), kept["headline"]["sure"], kept["tiles"][0]["value"]), ("CALL", "close", "26% / 32%"))
        warned = next(w["text"] for w in kept["warnings"] if w["code"] == "close")
        self.assertTrue(warned.startswith("Close: the call takes 26% with the points for play after the flop, and "
                                          "you have 32%."), warned)
        # ... and with sixteen points to spare it is a plain call: no "close" pill, no "Close:" warning
        kept = A.advise(tournament([12] * 8, BB, "A9s", acts=[(UTG, "raise", 2)]))
        self.assertEqual((verb(kept), kept["headline"]["sure"], kept["tiles"][0]["value"]), ("CALL", "standard", "26% / 42%"))
        self.assertNotIn("close", codes(kept))
        # C2 and its kin: a close all-in names the line it is close to, whatever happened before
        self.assertEqual(A.ENGINE_ALLIN_LINES["reraised"], (0.50, "against a re-raise"))
        with engine_says("FOLD", "standard", why=["not strong enough to play for stacks against a 3-betting range"],
                         numbers=["their 3-bet range ~6.7% [x]; your equity 37%",
                                  "4-bet shove EV +0.15bb vs folding; they fold 52%; when called you have 31%"]):
            a = A.advise(tournament([18] * 8, CO, "KQs", acts=[(CO, "raise", 2), (BTN, "raise", 6)]))
        gain = next(t for t in a["tiles"] if t["label"] == "All-in against folding")
        self.assertEqual((verb(a), gain["value"], gain["note"]),
                         ("FOLD", "+0.15bb", "under the +0.50bb it takes against a re-raise"))
        # with more than 45bb the engine answers a re-raise by its equity rules: the fold is not made from the
        # all-in's number, so a small gain is not shown beside it
        with engine_says("FOLD", "standard", why=["dominated too often by a 3-betting range; let it go"],
                         numbers=["their 3-bet range ~6.7% [x]; your equity 36%",
                                  "4-bet shove EV +0.05bb vs folding; they fold 78%; when called you have 29%"]):
            a = A.advise(tournament([80] * 8, CO, "A4s", acts=[(CO, "raise", 2.2), (BTN, "raise", 6.6)]))
        self.assertEqual((verb(a), [t["label"] for t in a["tiles"]]), ("FOLD", ["Their range"]))

    def test_a5_a_raise_after_hero_called_is_not_folded_at_five_to_one(self):
        # the Spin fuzz: the big blind called a 2bb all-in, the button then raised to 3bb, and 8-6 was folded
        # for one big blind more into a pot of seven
        a = A.advise(spin([14.5, 2, 14.5], 2, "8h6d",
                          acts=[(0, "call", None), (1, "allin", None), (2, "call", None), (0, "raise", 3)]))
        self.assertEqual((verb(a), a["headline"]["follow"], a["headline"]["qualifier"]),
                         ("CALL", {"kind": "call"}, "the price"))
        self.assertIn("1bb more for a pot of 7bb: 7 to 1", a["reason"])
        self.assertEqual(a["source"], "A call at 5 to 1 or better after calling is never folded")
        # the tournament's rule "you only called and a player raised: fold" is for a real raise
        limped = [(UTG, "call", None), (BTN, "call", None)]
        a = A.advise(tournament([30] * 8, BTN, "7h6h", acts=limped + [(BB, "raise", 2)]))
        self.assertEqual(verb(a), "CALL")
        self.assertIn("5.5 to 1", a["reason"])
        self.assertEqual(a["also"], "Without the price: FOLD (the rule after a call).")
        a = A.advise(tournament([30] * 8, BTN, "7h6h", acts=limped + [(BB, "raise", 5)]))
        self.assertEqual(verb(a), "FOLD")
        self.assertIn("the sheet's rule", a["source"])

    def test_a5_a_raise_over_a_short_all_in_is_the_first_raise(self):
        # under the gun is all-in for 1.4bb and the cutoff raises to 4.2bb.  Read as "a raise and a re-raise"
        # the big blind folded queens and ace-king; it is one raise, with a short stack's chips in the pot.
        stacks = [30] * 8
        stacks[UTG] = 1.4
        acts = [(UTG, "allin", None), (CO, "raise", 4.2)]
        s = tournament(stacks, BB, "QQ", acts=acts)
        seen = A.read_table(s, s.view())
        # (listed after the raise, as a call of it: the engine then counts the short stack's chips in the pot)
        self.assertEqual([(act.idx, act.kind) for act in seen.acts], [(CO, "raise"), (UTG, "call")])
        self.assertEqual(A.what_happened(seen).kind, "raise")
        for hand in ("QQ", "AKs"):
            a = A.advise(tournament(stacks, BB, hand, acts=acts))
            self.assertNotEqual(verb(a), "FOLD", hand)
            self.assertNotIn("re-raise", a["spot"])
        self.assertEqual(a["spot"], "AKs in the big blind, 30bb, UTG is all-in for 1.3bb, CO raises to 4.2bb")
        self.assertEqual(verb(A.advise(tournament(stacks, BB, "J8o", acts=acts))), "FOLD")
        # two real raises are still a raise and a re-raise, and a real all-in stays one
        a = A.advise(tournament([50] * 8, BTN, "QQ", acts=[(UTG, "raise", 2.3), (HJ, "raise", 7)], left=800))
        self.assertEqual(verb(a), "FOLD")
        stacks[UTG] = 8
        s = tournament(stacks, BB, "QQ", acts=[(UTG, "allin", None), (CO, "raise", 20)])
        self.assertEqual([act.kind for act in A.read_table(s, s.view()).acts], ["allin", "raise"])


class FinalGate(unittest.TestCase):
    """The faults the final gate confirmed in the adapter: one test each (G-A6 to G-A8)."""

    def test_g_a6_the_big_blinds_sheet_list_is_the_printed_one_for_the_raisers_seat(self):
        # Under a row of part 3 the sheet prints what changes against the other seat of the raiser's group:
        # "if the raise came from LJ, do not call: ...", "if the raise came from BTN, call as well: ...".
        checked = 0
        for players in (6, 7, 8):
            names = A.TAG.seats(players)                            # players behind -> seat name
            for key, row in A.TAG.table(players)["vs_raise"].items():
                if not key.endswith("|bb"):
                    continue
                for line in A.TAG.seat_lines(players, row):
                    found = re.fullmatch(r"if the raise came from (\S+), (do not call|call as well): (.+)", line)
                    self.assertIsNotNone(found, line)
                    behind = next(nb for nb, name in names.items() if name == found.group(1))
                    s = tournament([30] * players, players - 1, "AA", acts=[(players - 1 - behind, "raise", 2.2)])
                    seen = A.read_table(s, s.view())
                    hands, words = A.big_blind_sheet_list(seen, A.what_happened(seen))
                    self.assertIn("against a raise from " + found.group(1), words)
                    on_list, named = parse_range(hands), parse_range(found.group(3))
                    wanted = 0.0 if found.group(2) == "do not call" else 1.0
                    for hand in range(169):
                        if named[hand] >= 0.5:
                            self.assertEqual(on_list[hand], wanted, (players, line, HANDS[hand]))
                            checked += 1
        self.assertGreater(checked, 40)
        # the two answers of the report.  Q9o against a lojack raise: the sheet prints "do not call"
        a = A.advise(tournament([30] * 8, BB, "Qs9d", acts=[(LJ, "raise", 2.2)]))
        self.assertEqual(verb(a), "FOLD")
        self.assertNotIn("on the sheet's big blind list", a["source"])
        self.assertIn("not on its list for the big blind with 25bb or more against a raise from LJ",
                      [t["note"] for t in a["tiles"]])
        # ... and against the hijack, the seat the row is printed for, the close call stays
        a = A.advise(tournament([30] * 8, BB, "Qs9d", acts=[(HJ, "raise", 2.2)]))
        self.assertEqual(verb(a), "CALL")
        self.assertIn("the engine's close call is on the sheet's big blind list", a["source"])
        # K2o against a button raise: the sheet prints "call as well", so "not on its list" is not said; the
        # fold before the money is for what the hand is
        a = A.advise(tournament([40] * 8, BB, "Ks2d", acts=[(BTN, "raise", 2.3)]))
        self.assertEqual(verb(a), "FOLD")
        text = " ".join([a["reason"]] + [t["note"] for t in a["tiles"]])
        self.assertNotIn("not on its list", text)
        self.assertNotIn("not a hand the sheet calls", text)
        self.assertIn("not a hand that makes top pair or a real draw", a["reason"])
        # against the cutoff, the seat the row is printed for, K2o is not on the list
        a = A.advise(tournament([40] * 8, BB, "Ks2d", acts=[(CO, "raise", 2.3)]))
        self.assertNotIn("not a hand that makes top pair or a real draw", a["reason"])

    def test_g_a7_the_chart_behind_callers_is_the_row_the_answer_came_from(self):
        def cells(chart, code):
            return {HANDS[k] for k in range(169) if chart["cells"][k // 13][k % 13] == code}

        def raise_list(session):
            spot = A.engine_spot(A.read_table(session, session.view()), A.Prizes(), A.Prizes(), {}, False)
            numbers = " | ".join(A.engine_advise(spot).numbers)
            return {HANDS[k] for k, w in enumerate(parse_range(re.search(r"isolation range: .*?\[(.*?)\]", numbers).group(1)))
                    if w >= 0.5}

        one_caller = [(LJ, "call", None)]
        # 20bb: the sheet's "17 to 24bb: without T8s, 98s, 87s, 76s", and "no calling along"
        s = tournament([20] * 8, CO, "7s2d", acts=one_caller)
        chart = A.advise(s)["chart"]
        self.assertEqual(chart["title"], "Sheet: cutoff behind 1 caller, 20bb")
        self.assertEqual(cells(chart, "r"), raise_list(s))
        self.assertFalse({"T8s", "98s", "87s", "76s"} & cells(chart, "r"))
        self.assertEqual(cells(chart, "c"), set())
        self.assertEqual([item["label"] for item in chart["legend"]], ["Raise", "Fold"])
        # 40bb: the deep row, with its calls
        s = tournament([40] * 8, CO, "7s2d", acts=one_caller)
        chart = A.advise(s)["chart"]
        self.assertEqual(cells(chart, "r"), raise_list(s))
        self.assertTrue({"T8s", "98s", "87s", "76s"} <= cells(chart, "r"))
        self.assertEqual(cells(chart, "c"), {"22", "65s", "54s"})
        # four callers: the sheet has no row ("fewer hands again with each caller"), so not the three-caller one
        four = [(UTG, "call", None), (UTG1, "call", None), (LJ, "call", None), (HJ, "call", None)]
        s = tournament([40] * 8, BTN, "7s2d", acts=four)
        chart = A.advise(s)["chart"]
        self.assertEqual(chart["title"], "Button behind 4 callers, 40bb")
        self.assertEqual(cells(chart, "r"), raise_list(s))
        self.assertNotIn("44", cells(chart, "r"))                   # the three-caller row raises 44+
        self.assertTrue({"44", "87s"} <= cells(chart, "c"))
        # and every answer is the cell the chart shows for the hand
        for stack, acts, seat in ((20, one_caller, CO), (40, one_caller, CO), (40, four, BTN)):
            for hand, cards in (("98s", "9s8s"), ("22", "2s2d"), ("44", "4s4d"), ("A9s", "As9s"), ("KJo", "KsJd")):
                a = A.advise(tournament([stack] * 8, seat, cards, acts=acts))
                wanted = {"RAISE": "r", "CALL": "c", "FOLD": "f"}[verb(a)]
                self.assertEqual(hero_cell(a["chart"]), wanted, (stack, len(acts), hand, verb(a)))

    def test_g_a8_a_fold_is_never_drawn_in_the_colour_of_a_play(self):
        # the re-raise chart's third colour is "Re-raise as a bluff": a folded hand is not shown in it
        for name, session in (
                ("the engine's chart calls", tournament([40] * 8, BB, "Ks2d", acts=[(BTN, "raise", 2.3)])),
                ("the engine's chart bluffs", tournament([26] * 8, SB, "KsQs", acts=[(CO, "raise", 2.2)]))):
            with self.subTest(name):
                a = A.advise(session)
                self.assertEqual(verb(a), "FOLD")
                self.assertIn("Re-raise as a bluff", [item["label"] for item in a["chart"]["legend"]])
                self.assertEqual(hero_cell(a["chart"]), "f")
        # a chart of the sheet has no third colour at all
        a = A.advise(tournament([20] * 8, CO, "9s8s", acts=[(LJ, "call", None)]))
        self.assertEqual((verb(a), hero_cell(a["chart"])), ("FOLD", "f"))
        # what the chart itself calls "Close" stays: that is the calculation's own word for the hand
        for kind in ("fold", "check"):
            close = A.range_chart("t", "AKo", {"r": [0.0] * 169, "x": parse_range("AKo")},
                                  legend=(("r", "All-in"), ("x", "Close"), ("f", "Fold")))
            self.assertEqual(hero_cell(A.hero_cell_as_played(close, HANDS.index("AKo"), kind)), "x")
            played = A.range_chart("t", "AKo", {"r": parse_range("AKo")}, legend=(("r", "All-in"), ("x", "Close"), ("f", "Fold")))
            self.assertEqual(hero_cell(A.hero_cell_as_played(played, HANDS.index("AKo"), kind)), "f")

    def test_g_a9_a_call_of_a_re_raise_states_its_plan_and_the_flop_keeps_it(self):
        # Queens in the hijack with 45bb, the big blind re-raises: since the gate the engine calls (it folded),
        # on the plan "after the flop the stack goes in with an overpair, top pair or better".
        def called(cards, flop, hero=HJ, stack=45, open_to=2.3, to=8.7, **more):
            s = tournament([stack] * 8, hero, cards, acts=[(hero, "raise", open_to), (BB, "raise", to)], **more)
            first = A.advise(s)
            s.do("act", seat=1, kind="call")
            s.do("set_cards", slot="flop", text=flop)
            return s, first, seat_of(BB, hero, 8)

        for style in ("survive", "cash"):
            with self.subTest(style=style):
                s, first, villain = called("QsQd", "9h7c2d", style=style)
                self.assertEqual((verb(first), first["guard"]), ("CALL", "none"))
                self.assertEqual(first["plans"], [A.STACK_IN_PLAN])
                s.do("act", seat=villain, kind="bet", amount=round(s.view()["hand"]["pot"] / 2))
                self.assertEqual(verb(A.advise(s)), "CALL")
                s.do("act", seat=1, kind="call")
                s.do("set_cards", slot="turn", text="4s")
                s.do("act", seat=villain, kind="allin")             # 26.7bb into 37.8bb: less than a pot behind
                a = A.advise(s)
                self.assertEqual((verb(a), a["headline"]["qualifier"], a["headline"]["follow"]),
                                 ("CALL", "as planned", {"kind": "call"}))
                self.assertIn("By the numbers alone: FOLD", a["also"])
                self.assertIn("the plan made with your call before the flop", a["source"])
                self.assertEqual({t["note"] for t in a["tiles"] if t["label"] in ("Equity", "Need / have")},
                                 {"by the numbers alone"})
                self.assertNotIn("engine", codes(a))                # "folding a strong hand here ..." was about the fold
        # the same when a bet of the user's is raised all-in on the flop
        s, _first, villain = called("QsQd", "9h7c2d")
        s.do("act", seat=villain, kind="check")
        s.do("act", seat=1, **A.advise(s)["headline"]["follow"])
        s.do("act", seat=villain, kind="allin")
        self.assertEqual((verb(A.advise(s)), A.advise(s)["headline"]["qualifier"]), ("CALL", "as planned"))
        # no overpair and no top pair: the plan says nothing, the fold stands
        s, _first, villain = called("QsQd", "Kh7c2d")
        s.do("act", seat=villain, kind="bet", amount=round(s.view()["hand"]["pot"] / 2))
        self.assertEqual(verb(A.advise(s)), "FOLD")
        # a call the coach did not advise carries no plan: queens under the gun with 35bb were a fold
        s, first, villain = called("QsQd", "9h7c2d", hero=UTG, stack=35, open_to=2.2, to=7.9)
        self.assertEqual((verb(first), first["plans"]), ("FOLD", []))
        s.do("act", seat=villain, kind="allin")
        a = A.advise(s)
        self.assertNotEqual(a["headline"]["qualifier"], "as planned")
        self.assertNotIn("the plan made with your call", a["source"])
        # and the all-in plan never just calls a re-raise, so it has no such plan to keep
        s, first, villain = called("QsQd", "9h7c2d", plan="allin")
        self.assertEqual((verb(first), first["plans"]), ("ALL-IN", []))
        s.do("act", seat=villain, kind="allin")
        self.assertNotEqual(A.advise(s)["headline"]["qualifier"], "as planned")

    def test_g_a9_the_sheets_row_for_a_re_raised_raise_in_both_plans(self):
        def cells(chart, code):
            return {HANDS[k] for k in range(169) if chart["cells"][k // 13][k % 13] == code}

        # with all moves the chart is the sheet's row, its call list included ("call QQ" under the gun)
        acts = [(UTG, "raise", 2.2), (BB, "raise", 7.9)]
        row = A.TAG.table(8)["reraised"]["early"]
        chart = A.advise(tournament([35] * 8, UTG, "AsKd", acts=acts))["chart"]
        self.assertEqual(chart["title"], "Sheet: you raised and were re-raised, 45bb or less")
        self.assertEqual(cells(chart, "c"), {HANDS[k] for k, w in enumerate(parse_range(row["call_short"])) if w >= 0.5})
        self.assertEqual(cells(chart, "c"), {"QQ"})
        self.assertIn("Call", [item["label"] for item in chart["legend"]])
        # the all-in plan never just calls: its chart is all-in or fold, and so is its answer
        a = A.advise(tournament([35] * 8, UTG, "QsQd", acts=acts, plan="allin"))
        self.assertEqual(verb(a), "FOLD")
        self.assertEqual([item["label"] for item in a["chart"]["legend"]], ["All-in", "Fold"])
        self.assertEqual(cells(a["chart"], "c"), set())
        # "over 40bb only aces and kings" is the rule of the first-in and over-a-raise charts.  It is not said
        # beside an all-in the sheet's deeper rows make: queens re-raised with 45bb, ace-king after two raises
        said = "Over 40bb the all-in plan only moves all-in with aces and kings."
        for name, session, wanted, shown in (
                ("re-raised", tournament([45] * 8, HJ, "QsQd", acts=[(HJ, "raise", 2.3), (BB, "raise", 8.7)],
                                         plan="allin"), "ALL-IN", False),
                ("a raise and a re-raise", tournament([45] * 8, BTN, "AsKs", acts=[(UTG, "raise", 2.3), (HJ, "raise", 7)],
                                                      plan="allin"), "ALL-IN", False),
                ("first in", tournament([45] * 8, HJ, "QsQd", plan="allin"), "FOLD", True),
                ("one raise", tournament([45] * 8, BTN, "QsQd", acts=[(HJ, "raise", 2.3)], plan="allin"), "FOLD", True)):
            with self.subTest(name):
                a = A.advise(session)
                self.assertEqual(verb(a), wanted)
                self.assertEqual(said in [w["text"] for w in a["warnings"]], shown)

    def test_g_a3_aces_and_kings_have_no_limit_in_the_all_in_chart(self):
        # The chart moves in with AA and KK up to its deepest column and beyond it ("over 40bb only AA, KK").
        # Close to the money "an all-in up to 20bb" stood beside an ALL-IN with 21.5bb, also in the hand's cell.
        row, column = divmod(HANDS.index("KK"), 13)
        for stack, left in ((18.5, 240), (21.5, 240), (18.5, 400)):
            with self.subTest(stack=stack, left=left):
                stacks = [30.0] * 6
                stacks[0] = stack
                a = A.advise(tournament(stacks, 0, "KsKd", left=left, plan="allin"))
                self.assertEqual(verb(a), "ALL-IN")
                self.assertEqual(a["chart"]["numbers"][row][column], "all-in with any stack")
                text = " ".join([a["reason"]] + [t["value"] for t in a["tiles"]])
                self.assertNotIn("up to 20bb", text)
                self.assertNotIn("up to 40bb", text)
        # queens do have the limit, in the user's own chips close to the money
        self.assertEqual(a["chart"]["numbers"][2][2], "all-in up to 40bb")
        stacks = [30.0] * 6
        stacks[0] = 18.5
        close = A.advise(tournament(stacks, 0, "QsQd", left=240, plan="allin"))
        self.assertEqual(close["chart"]["numbers"][2][2], "all-in up to 20bb this close to the money")
        # the line under an answer with all moves says the same
        stacks = [30.0] * 8
        stacks[BTN] = 14
        a = A.advise(tournament(stacks, BTN, "KsKd", left=240, style="cash"))
        self.assertEqual(a["flip"], "The all-in chart moves in with KK with any stack from this seat before the money.")

    def test_g_a1_two_big_stacks_at_one_table_under_a_top_heavy_ladder(self):
        # 7,000 entrants, 1,100 paid, two thirds of the pool to the winner; the money has just been reached.
        # Hero holds 20 average stacks and a player at the table 25.  The closed formula took that player's
        # chance to be ahead of hero at the field's moment and said 1.22 points of risk premium; the integral
        # says 0.93.  (More than 0.1 points apart is the gate's line.)
        from poker_coach.icm import Prizes, default_payouts
        entrants, paid = 7000, 1100
        shape = [k ** -2.2 for k in range(1, paid + 1)]
        scale = (entrants - 1.2 * paid) / sum(shape)
        raw, ladder, k = [1.2 + scale * w for w in shape], [], 0
        while k < paid:                                 # places beyond the 60th in groups, as lobbies print them
            size = 1 if k < 60 else max(3, k // 5)
            ladder += [sum(raw[k:k + size]) / len(raw[k:k + size])] * len(raw[k:k + size])
            k += size
        average = entrants * 10000.0 / paid
        for stacks in ([20 * average, 0.1 * average, 25 * average],
                       [20 * average, 0.2 * average, 0.3 * average, 0.25 * average, 0.4 * average, 30 * average]):
            field = paid - len(stacks)
            exact = Prizes(ladder, field, average).risk_premium(stacks, 0, len(stacks) - 1)
            closed = Prizes(ladder, field, average, large=True).risk_premium(stacks, 0, len(stacks) - 1)
            self.assertAlmostEqual(100 * exact, 0.93, delta=0.01)
            self.assertAlmostEqual(100 * closed, 100 * exact, delta=0.02)
        # and the ordinary ladder with the same two stacks: 0.09 points apart before, now under 0.01
        ladder = default_payouts(entrants, paid)
        stacks = [20 * average, 0.2 * average, 0.3 * average, 0.25 * average, 0.4 * average, 30 * average]
        exact = Prizes(ladder, paid - 6, average).risk_premium(stacks, 0, 5)
        closed = Prizes(ladder, paid - 6, average, large=True).risk_premium(stacks, 0, 5)
        self.assertAlmostEqual(100 * closed, 100 * exact, delta=0.01)

    def test_g_a4_the_short_all_ins_chips_are_in_the_pot_the_answer_prices(self):
        # Under the gun is all-in for 2.975bb and the cutoff raises to 7bb.  The big blind calls 6bb into
        # 1 (antes) + 0.5 + 1 + 2.975 + 7 = 12.475bb: 32%.  Passed as a call of the big blind, the engine left
        # the short stack's chips out and the tile said 39%.
        stacks = [30] * 8
        stacks[UTG] = 3.1
        acts = [(UTG, "allin", None), (CO, "raise", 7)]
        a = A.advise(tournament(stacks, BB, "9s9d", acts=acts))
        self.assertEqual(verb(a), "CALL")
        need = next(t for t in a["tiles"] if t["label"] == "Need / have")
        self.assertIn("the price (32%)", need["note"])
        s = tournament(stacks, BB, "9s9d", acts=acts)
        self.assertAlmostEqual(A.call_price(A.read_table(s, s.view())), 6 / 18.475, places=4)   # the table's own count
        # two short all-ins and a raise: both are callers of that raise, in the order they acted
        stacks[UTG], stacks[HJ] = 1.5, 2.5
        s = tournament(stacks, BTN, "QsQd", acts=[(UTG, "allin", None), (HJ, "allin", None), (CO, "raise", 7)])
        seen = A.read_table(s, s.view())
        self.assertEqual([(act.idx, act.kind) for act in seen.acts], [(CO, "raise"), (UTG, "call"), (HJ, "call")])
        self.assertEqual((A.what_happened(seen).kind, verb(A.advise(s))), ("raise", "ALL-IN"))
        # a short all-in that only an all-in came over stays what it was, and so does one of 3bb or more
        stacks = [30] * 8
        stacks[UTG], stacks[CO] = 2, 15
        s = tournament(stacks, BB, "QsQd", acts=[(UTG, "allin", None), (CO, "allin", None)])
        self.assertEqual([act.kind for act in A.read_table(s, s.view()).acts], ["allin", "allin"])
        stacks = [30] * 8
        stacks[UTG] = 3.125                             # all-in for exactly 3bb after the ante
        s = tournament(stacks, BB, "QsQd", acts=[(UTG, "allin", None), (CO, "raise", 7)])
        self.assertEqual([(act.idx, act.kind) for act in A.read_table(s, s.view()).acts], [(UTG, "allin"), (CO, "raise")])

    def test_g_a4_the_five_to_one_call_is_not_forced_on_the_bubble_for_a_third_of_the_chips(self):
        # Three players and the user call the big blind, the big blind raises to 2.125bb, two of them call:
        # 1.125bb more for a pot of 8.875bb, 7.9 to 1.  With 4bb at the start that call is 39% of what is left.
        # One place from the money 72o has 13% against the three of them and the prize maths wants 18%.
        def spot(stack, left, **more):
            stacks = [30, 28, 35, 26, 24, 40, 22, 33]
            stacks[CO] = stack
            acts = [(UTG, "call", None), (HJ, "call", None), (CO, "call", None), (BB, "raise", 2.125),
                    (UTG, "call", None), (HJ, "call", None)]
            return A.advise(tournament(stacks, CO, "7s2d", acts=acts, left=left, **more))

        for more in (dict(style="cash"), dict(style="survive"), dict(style="maxev"), dict(plan="allin")):
            for left in (151, 152):
                with self.subTest(left=left, **more):
                    a = spot(4, left, **more)
                    self.assertEqual(verb(a), "FOLD")
                    self.assertTrue(a["source"].endswith(
                        "the sheet's rule (on the bubble the price alone is no call for a third or more of your chips)"))
        # the rule itself stays: away from the bubble, in the money, and for a small part of the chips on it
        for stack, left in ((4, 165), (4, 400), (4, 100), (8, 151)):
            with self.subTest(stack=stack, left=left):
                a = spot(stack, left)
                self.assertEqual((verb(a), a["headline"]["qualifier"]), ("CALL", "the price"))
                self.assertTrue(a["source"].endswith("a call at 5 to 1 or better after calling is never folded"))
        # the price is the real pot's: antes 1bb, the dead small blind, the raise, two callers, the user's own call
        a = spot(8, 400)
        self.assertEqual(a["tiles"][0]["value"], "7.9 to 1")
        self.assertIn("1.1bb more for a pot of 8.9bb", a["reason"])
        # and the edge: 5 to 1 is called, 4.9 to 1 is the sheet's fold
        for to, wanted in ((2.125, "CALL"), (2.15, "FOLD")):
            acts = [(UTG, "call", None), (BTN, "call", None), (BB, "raise", to), (UTG, "fold", None)]
            self.assertEqual(verb(A.advise(tournament([30] * 8, BTN, "7s2d", acts=acts))), wanted, to)

    def test_g_a5_a_player_is_they_in_the_engines_sentences_too(self):
        # found by random play: "... a raiser who has committed his stack" as the reason on the screen
        stacks = [20, 20, 6, 20, 4.3]                   # five players; the button raises to 4bb of a 6bb stack
        a = A.advise(tournament(stacks, 4, "Ac5h", acts=[(2, "raise", 4)], left=None))
        self.assertEqual(a["reason"], "You beat the price against a raiser who has committed their stack.")
        for theirs in ("you beat the price against a raiser who has committed his stack",
                       "re-raise to play the short stack heads-up: the caller folds most of his hands"):
            self.assertNotRegex(A.plain(theirs), r"\b(he|his|him)\b")
            self.assertIn("their", A.plain(theirs))


class LastCorrections(unittest.TestCase):
    """Two answers the final gate left open, corrected in the engine afterwards."""

    def test_a_fold_that_is_ahead_of_the_price_is_a_close_fold_and_names_the_call(self):
        # queens raised under the gun and re-raised by the big blind, 35bb, 250 places from the money: 45%
        # against a call that needs 34% and a few points of risk premium.  Under the 10 points that make it a
        # call, so a fold, but a close one in every style, and the note names the call (not the all-in's number)
        for style in ("survive", "cash", "maxev"):
            with self.subTest(style=style):
                a = A.advise(tournament([35] * 8, UTG, "QsQd", [(UTG, "raise", 2.2), (BB, "raise", 8.4)], style=style))
                self.assertEqual(a["headline"]["verb"], "FOLD")
                self.assertEqual(a["headline"]["sure"], "close")
                close = [w["text"] for w in a["warnings"] if w["code"] == "close"]
                self.assertEqual(len(close), 1, a["warnings"])
                self.assertRegex(close[0], r"^Close: the call needs \d+% with the prizes counted and you have \d+%; "
                                           r"calling is nearly as good\.")
                self.assertNotIn("all-in earns", close[0])

    def test_an_all_in_and_a_raise_over_it_is_not_only_for_premiums(self):
        # under the gun is all-in for 6bb, the cutoff raises to 15bb, the user has tens on the button with 40bb
        stacks, acts = [6] + [40] * 7, [(UTG, "allin", 6), (CO, "raise", 15)]
        a = A.advise(tournament(stacks, BTN, "TsTd", acts))                       # survive: a clear edge stands
        self.assertEqual(a["headline"]["verb"], "ALL-IN")
        self.assertIn("raised over it", a["reason"])
        self.assertIn("CLEAR EDGE", a["source"])
        a = A.advise(tournament(stacks, BTN, "TsTd", acts, style="cash"))         # cash first: the chart's fold
        self.assertEqual(a["headline"]["verb"], "FOLD")
        self.assertIn("SURVIVAL FOLD (engine: ALL-IN", a["source"])
        a = A.advise(tournament(stacks, BTN, "AsTd", acts))                       # not ahead of the raiser's hands
        self.assertEqual(a["headline"]["verb"], "FOLD")

    def test_a_close_all_in_over_an_all_in_and_a_raise_names_the_bar_it_was_measured_against(self):
        # an all-in the rule makes must earn +1.00bb (twice the +0.50bb of JJ+ and ace-king).  When it is close, the
        # note names that bar: it said "after a raise and a re-raise it takes +0.50bb"
        stacks, acts = [6] + [40] * 7, [(UTG, "allin", 6), (CO, "raise", 15)]
        s = tournament(stacks, BTN, "TsTd", acts, style="maxev")
        seen = A.read_table(s, s.view())
        self.assertEqual(A.engine_line(seen, {"allin_bar_bb": 1.0, "ev": 1.2}, A.what_happened(seen)),
                         (1.0, "over an all-in and a raise"))
        a = A.advise(s)
        self.assertEqual(a["headline"]["verb"], "ALL-IN")
        # ace-queen is ahead of every hand that might raise there, but not of the better half of them: a fold
        a = A.advise(tournament(stacks, BTN, "AsQd", acts, style="maxev"))
        self.assertEqual(a["headline"]["verb"], "FOLD")
        self.assertIn("against the better half of them this hand has only", a["reason"])
        # queens in the same spot are on the list: their bar is the usual one, and nothing is close
        a = A.advise(tournament(stacks, BTN, "QsQd", acts, style="maxev"))
        self.assertEqual((a["headline"]["verb"], a["headline"]["sure"]), ("ALL-IN", "clear"))

    def test_a_raiser_tagged_tight_keeps_the_all_in_over_an_all_in_and_a_raise_to_the_list(self):
        # the user tagged the cutoff nit: tens are no all-in against that player's raise over an all-in, in any style
        stacks, acts = [6] + [40] * 7, [(UTG, "allin", 6), (CO, "raise", 15)]
        for style in ("survive", "maxev"):
            with self.subTest(style=style):
                a = A.advise(tournament(stacks, BTN, "TsTd", acts, style=style, types={CO: "nit"}))
                self.assertEqual(a["headline"]["verb"], "FOLD")
                self.assertIn("CO is nit: from this player a raise over an all-in is a strong hand", a["reason"])
                self.assertNotIn("raised over it", a["reason"])
                # no "Their range 16%: you have 60% against it" beside a fold made because that range is not theirs
                self.assertNotIn("Their range", [tile["label"] for tile in a["tiles"]])


def spin_six(stacks_bb, hero, cards, acts=(), bb=20, prizes=None, size=6):
    """A six-seat Spin hand: players in acting order, first to act first (the last three are BTN, SB, BB)."""
    n = len(stacks_bb)
    s = Session(save=False)
    s.do("new_session", mode="spin", size=size, start_stack=300)
    s.do("set_level", text=f"{bb // 2}/{bb}")
    for seat in range(n + 1, size + 1):
        s.do("clear_seat", seat=seat)
    s.do("set_button", seat=seat_of(max(0, n - 3), hero, n))
    for index, stack in enumerate(stacks_bb):
        s.do("set_stack", seat=seat_of(index, hero, n), text=str(int(stack * bb)))
    if prizes:
        s.do("set_tournament", field="payouts", text=prizes)
    s.do("deal", hero_cards=cards)
    for index, kind, amount in acts:
        s.do("act", seat=seat_of(index, hero, n), kind=kind, amount=None if amount is None else amount * bb)
    return s


class SpinSixPlayers(unittest.TestCase):
    """Spin & Gold with six players (GGPoker's 6-Max): the table, the prizes, and who answers."""

    def test_the_table_has_three_seats_or_six(self):
        from poker_coach.app.model import ModelError
        s = Session(save=False)
        s.do("new_session", mode="spin", size=6)
        view = s.view()
        self.assertEqual((view["table"]["size"], view["settings"]["size_choices"]), (6, [3, 6]))
        s.do("deal", hero_cards="AhKd")
        self.assertEqual([seat["pos"] for seat in s.view()["table"]["seats"]], ["BTN", "SB", "BB", "LJ", "HJ", "CO"])
        s.do("discard_hand")
        for op, more in (("new_game", {"size": 5}), ("set_size", {"size": 4}), ("new_session", {"mode": "spin", "size": 4})):
            with self.assertRaises(ModelError) as refused:
                s.do(op, **more)
            self.assertIn("3 or 6 seats", str(refused.exception))
        s.do("new_game", size=3)                                    # the other size is a new game
        self.assertEqual(s.view()["table"]["size"], 3)
        self.assertEqual(Session(save=False).view()["settings"]["size_choices"], None)      # a tournament: any size

    def test_prizes_are_typed_for_one_game(self):
        s = Session(save=False)
        s.do("new_session", mode="spin", size=6)
        self.assertEqual(s.view()["strip"]["payouts"], None)        # one prize: the winner takes all
        s.do("set_tournament", field="payouts", text="8 2")
        self.assertEqual(s.view()["strip"]["payouts"], [8.0, 2.0])
        for seat in (3, 4, 5, 6):                                   # four players are out; the user goes out second
            s.do("set_stack", seat=seat, text="0")
        s.do("set_stack", seat=1, text="0")
        self.assertIn("You are out in place 2: a paid place.", " ".join(s._toast))
        view = s.view()
        self.assertEqual((view["strip"]["game"]["over"], view["strip"]["tally"]), ("lost", {"games": 1, "wins": 0}))
        s.do("new_game")                                            # the next game has its own multiplier
        self.assertEqual(s.view()["strip"]["payouts"], None)

    def test_four_to_six_players_are_answered_by_the_engine_on_chips(self):
        lj, hj, co, btn, sb, bb = range(6)
        a = A.advise(spin_six([15] * 6, lj, "As9d"))
        self.assertIn("Chip-EV engine: 6 players, one prize", a["source"])
        self.assertIn(a["headline"]["verb"], ("FOLD", "RAISE", "ALL-IN"))
        a = A.advise(spin_six([10] * 6, btn, "AsKd", [(lj, "fold", None), (hj, "fold", None), (co, "fold", None)]))
        self.assertIn(a["headline"]["verb"], ("ALL-IN", "RAISE"))
        a = A.advise(spin_six([15] * 6, bb, "AsAd", [(lj, "fold", None), (hj, "fold", None), (co, "allin", None),
                                                      (btn, "fold", None), (sb, "fold", None)]))
        self.assertEqual(a["headline"]["verb"], "CALL")
        self.assertIn("Four players or more: the engine with all moves, on chips", a["context"]["gear"])
        for left in (5, 4):                                         # after the first players are out
            a = A.advise(spin_six([12] * left, 0, "AsKd"))
            self.assertIn(f"Chip-EV engine: {left} players, one prize", a["source"])
        # three left with one prize: the solved chart, as in the three-player game
        a = A.advise(spin_six([20, 20, 8], 2, "As5d", [(0, "fold", None), (1, "allin", None)]))
        self.assertIn("Spin table", a["source"])

    def test_two_prizes_are_counted_by_icm_until_two_players_are_left(self):
        lj = 0
        a = A.advise(spin_six([15] * 6, lj, "As9d", prizes="8 2"))
        self.assertIn("ICM for the prizes typed (8 / 2): 6 players", a["source"])
        self.assertIn("by ICM for the prizes typed", a["context"]["gear"])
        a = A.advise(spin_six([10] * 3, 0, "Ks7s", prizes="8 2"))   # three left: the bubble of the two prizes
        self.assertIn("ICM for the prizes typed (8 / 2): 3 players", a["source"])
        a = A.advise(spin_six([12, 12], 0, "Qs8d", prizes="8 2"))   # heads-up both have the second prize: chips
        self.assertIn("Spin table", a["source"])
        # the same three-player bubble: a short stack's all-in is called tighter by ICM than on chips
        spot = ([20, 8, 20], 2, "Ks9d", [(0, "fold", None), (1, "allin", None)])
        on_chips, by_icm = A.advise(spin_six(*spot)), A.advise(spin_six(*spot, prizes="8 2"))
        self.assertIn("Spin table", on_chips["source"])
        self.assertIn("ICM for the prizes typed", by_icm["source"])
        self.assertEqual(on_chips["headline"]["verb"], "CALL")

    def test_the_page_offers_six_players_and_marks_the_seat_that_is_up(self):
        import os
        static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "poker_coach", "app", "static")
        with open(os.path.join(static, "render.js"), encoding="utf-8") as fh:
            js = fh.read()
        with open(os.path.join(static, "app.css"), encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn('{value: "6", label: "6 players (6-Max)"}', js)              # the first-run form
        self.assertIn('emit({op: "new_game", size: n, ui: closed})', js)             # the table menu
        self.assertIn('send: {op: "set_tournament", field: "payouts", ui: {edit: null}}', js)   # the strip's prizes
        # the seat that is up is yellow for every player, not only the user
        self.assertIn("const turn = acting != null && seat.seat === acting;", js)
        self.assertIn(".pod.turn{border:2px solid var(--yellow)", css)
        self.assertIn("button.pod.turn:hover{border-color:var(--yellow)}", css)
        self.assertIn(".actions .whose .eyebrow.up,.actions .whose .eyebrow.up+b{color:var(--yellow)}", css)


if __name__ == "__main__":
    unittest.main()
