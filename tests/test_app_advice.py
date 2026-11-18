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

from poker_coach.app import advice as A
from poker_coach.app.model import ModelError, Session
from poker_coach.cards import HANDS, card_str, parse_hand

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


def all_in_or_fold(stacks_bb, hero, cards, movers=()):
    """An All-In or Fold hand: four players in acting order (CO, BTN, SB, BB); ``movers`` moved all-in."""
    n = len(stacks_bb)
    s = Session(save=False)
    s.do("new_session", mode="aof", button=seat_of(n - 3, hero, n))
    for index, stack in enumerate(stacks_bb):
        s.do("set_stack", seat=seat_of(index, hero, n), text=str(stack))
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
    case.assertIn(answer["guard"], ("agrees", "survival", "off", "none"))
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
        a = A.advise(tournament(STACKS_A, BTN, "A5o", left=260))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("up to 15bb", a["reason"])
        self.assertIn("ALL-IN +0.55bb", a["also"])

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
        bubble = A.advise(tournament(stacks, BB, "99", acts=shove, left=152))
        self.assertEqual((verb(bubble), bubble["guard"]), ("FOLD", "survival"))
        self.assertIn("TT+, AQs+, AKo", bubble["reason"])
        self.assertIn("CALL, 60% against 53%", bubble["also"])
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
        a = A.advise(tournament(STACKS_A, BTN, "TT", acts=[(HJ, "allin", None), (CO, "allin", None)], left=185))
        self.assertEqual((verb(a), a["guard"]), ("FOLD", "survival"))
        self.assertIn("CALL", a["also"])

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
        self.assertEqual(a["headline"]["follow"], {"kind": "allin"})
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


if __name__ == "__main__":
    unittest.main()
