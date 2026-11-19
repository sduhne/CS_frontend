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
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("twice your stack", a["reason"])
        a = A.advise(tournament(STACKS_A, BTN, "A8o", left=152, style="maxev"))
        self.assertEqual((verb(a), a["guard"]), ("ALL-IN", "off"))
        self.assertEqual(a["tiles"][0]["value"], "+0.20bb")

    def test_T6_close_to_the_money_reads_twice_the_stack(self):
        # the table at 24bb folds A5o (an all-in up to 15bb).  The strict guard of "Cash first" follows it ...
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260, style="cash"))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("up to 15bb", a["reason"])
        self.assertIn("twice your stack", a["reason"])
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
        self.assertEqual(bubble["tiles"][-1], {"label": "The table says", "value": "FOLD", "note": "TT+, AQs+, AKo",
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
        self.assertIn("The full engine", a["also"])        # the second line, always

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
        self.assertIn("31% of the sit-out line", a["context"]["fold_clock"])


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
        self.assertIn("The engine alone: CALL", a["also"])  # the engine calls there
        self.assertEqual(a["spot"], "AsTd on Tc7h4s2dKh, BB bets 12bb into 18bb")
        # without the tag there is no rule to apply: the engine's call stands
        self.assertEqual(verb(self.river_bet_from_the_big_blind(None)), "CALL")

    def test_P4_close_call_with_icm_priced_in(self):
        # the bubble; the cutoff covers hero, raises to 3bb and moves all-in on the flop
        stacks = [30, 25, 18, 40, 30, 22, 16, 17]
        s = tournament(stacks, BB, "AhQd", acts=[(CO, "raise", 3)], left=152)
        s.do("act", seat=1, kind="call")
        s.do("set_cards", slot="flop", text="Qs8d3c")
        s.do("act", seat=1, kind="check")
        s.do("act", seat=seat_of(CO, BB, 8), kind="allin")
        a = A.advise(s)
        self.assertEqual(verb(a), "CALL")
        self.assertEqual(a["headline"]["sure"], "close")
        self.assertIn("close", codes(a))
        need, have = (int(x.strip("%")) for x in a["tiles"][1]["value"].split(" / "))
        self.assertTrue(have - 3 <= need <= have, (need, have))
        self.assertGreater(need, 55)                        # pot odds alone ask for 39%: the rest is the bubble


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
        self.assertEqual(a["headline"]["size_text"], "8BB")

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
        self.assertIn("orbits of blinds", a["context"]["fold_clock"])
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
        self.assertIn("twice your stack", a["reason"])
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
        self.assertIn("KeyError", answer["reason"])
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
        self.assertIn("The edge is thin (32% against 29%)", a["reason"])

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
            s = tournament([30, 25, 18, 40, 22, 12, 15, 20], BTN, "K9s", left=left)
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
        self.assertEqual((A.THIN_EV_BB_FAR, A.THIN_EV_BB_CLOSE), (0.30, 0.50))
        self.assertEqual((A.THIN_EDGE_POINTS_FAR, A.THIN_EDGE_POINTS_CLOSE), (4, 7))
        # the measure itself: an all-in by the engine's "all-in against folding", a call by have minus need,
        # and a play without a number counts as thin
        all_in = A.Play("ALL-IN", "allin", facts={"ev": 0.30})
        self.assertEqual(A.engine_edge(all_in, near=False), (False, "engine +0.30bb"))
        self.assertEqual(A.engine_edge(all_in, near=True), (True, "engine +0.30bb"))
        call = A.Play("CALL", "call", facts={"need": 0.47, "equity": 0.53, "ev": 2.0})
        self.assertEqual(A.engine_edge(call, near=False), (False, "53% against 47%"))
        self.assertEqual(A.engine_edge(call, near=True), (True, "53% against 47%"))
        self.assertEqual(A.engine_edge(A.Play("RE-RAISE", "raise"), near=False), (True, ""))
        # thin and the table folds: the survival fold, in both styles (K9s in the cutoff, +0.15bb)
        for style in (None, "cash"):
            a = A.advise(tournament(STACKS_B, CO, "K9s", style=style))
            self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"), style)
        thin = A.advise(tournament(STACKS_B, CO, "K9s"))
        self.assertIn("The edge is thin (+0.15bb)", thin["reason"])
        self.assertIn("with a clear edge", thin["flip"])
        # a clear edge far from the money: A8o on the button with 12bb at 300 left was a survival fold (+1.06bb)
        clear = A.advise(tournament(STACKS_A, BTN, "A8o", left=300))
        self.assertEqual(verb(clear), "ALL-IN")
        self.assertIn(clear["guard"], ("edge", "agrees"))

    def test_pre_7_seventeen_big_blinds_or_more_the_sheets_small_raise_not_a_fold(self):
        # 44 in the cutoff with 18bb: the engine moves all-in for +0.26bb, the table folds (all-in up to 16bb),
        # and the sheet raises 44 from the cutoff: the headline is that raise, with the plan against an all-in
        s = tournament([18] * 8, CO, "44")
        a = A.advise(s)
        self.assertEqual((verb(a), a["guard"]), ("RAISE", "survival"))
        self.assertEqual(a["headline"]["qualifier"], "survival raise")
        self.assertEqual(a["headline"]["follow"], {"kind": "raise", "to": 2000})
        self.assertIn("SURVIVAL RAISE (engine: ALL-IN +0.26bb): the sheet's small raise", a["source"])
        self.assertIn("raise, and fold to an all-in", a["reason"])
        self.assertTrue(a["plans"] and all(": FOLD" in line for line in a["plans"]), a["plans"])
        self.assertEqual(hero_cell(a["chart"]), "r")
        # the next answer keeps that plan
        s.do("act", seat=1, kind="raise", amount=2000)
        s.do("act", seat=seat_of(BB, CO, 8), kind="allin")
        self.assertEqual(verb(A.advise(s)), "FOLD")
        # a hand the sheet does not raise from that seat is still a fold: K2s in the small blind
        fold = A.advise(tournament([18] * 8, SB, "K2s"))
        self.assertEqual((verb(fold), fold["guard"]), ("FOLD", "survival"))

    def test_pre_8_a_read_lifts_the_guard_only_when_it_makes_the_play_safer(self):
        def first_in(**more):                       # 87s first in from the small blind with 10bb
            return A.advise(tournament([10] * 8, SB, "87s", **more))

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
                    self.assertIn("The engine alone: CALL, 33% against 18%", a["also"])
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
            # the exception is 9 to 24bb against 2.5bb or less: deeper, or against a bigger raise, the fold leads
            self.assertEqual(verb(A.advise(tournament([30] * 8, BB, "T2s", acts=small_raise))), "FOLD")
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
        self.assertEqual(a["tiles"][1]["note"], "table read at 5bb")
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
                    self.assertIn("on the bubble the table calls with", plan["reason"])
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
        self.assertRegex(limped["also"], r"^The full engine on these stacks: [A-Z-]+\.$")
        # (4) nothing typed about the tournament: the stage line says so, like the strip
        blank = A.advise(tournament(STACKS_A, BTN, "A8o", left=None))
        self.assertEqual(blank["context"]["stage"], "Stage unknown: enter players left and places paid.")
        known = A.advise(tournament(STACKS_A, BTN, "A8o"))
        self.assertTrue(known["context"]["stage"].startswith("Middle:"), known["context"]["stage"])


if __name__ == "__main__":
    unittest.main()
