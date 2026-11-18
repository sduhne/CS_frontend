"""The table app's model: seats, the hand machine, the session, the view.
Run: python -m unittest tests.test_app_model

The numbered cases are the 45 of the rules proposal.  "Table A" is its test
table: seats 1 to 6 with 10,000 each, blinds 100/200, no ante, button on
seat 1, so LJ is seat 4, HJ 5, CO 6, BTN 1 (hero), SB 2, BB 3.
"""

import copy
import json
import os
import random
import shutil
import tempfile
import unittest

from poker_coach import binary
from poker_coach import state as S
from poker_coach.app import defaults as D
from poker_coach.app.amounts import AmountError, fmt, fmt_bb, parse_amount, parse_blinds, parse_ladder, parse_payouts
from poker_coach.app.model import (BETTING, HERO, HandState, ModelError, Session, _deviated, build_hand,
                                   engine_state, icm_level, next_big_blind, preflop_order, replay,
                                   seat_labels, session_level, stage_of)
from poker_coach.preflop import pos_to_index
from poker_coach.ranges import PLAYER_TYPES, SEAT_LABELS, position_name

LJ, HJ, CO, BTN, SB, BB = 4, 5, 6, 1, 2, 3          # Table A


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def new_table(size=6, stack=10000, blinds="100/200/0", button=1, stacks=None, bb_ante=False, away=(),
              short_post=None, remaining=None, paid=None, deal=True):
    """A tournament session in memory, set up through intents like the browser would."""
    s = Session(save=False)
    s.do("new_session", size=size, start_stack=stack, button=button)
    if bb_ante:
        s.do("set_ante_kind", kind="bb")
        blinds = "/".join(blinds.split("/")[:2])        # the big blind pays one big blind for the table
    s.do("set_level", text=blinds)
    stacks = stacks or {}
    s.do("set_stacks", values=[stacks.get(seat, stack) for seat in range(1, size + 1)])    # every stack typed
    for seat in away:
        s.do("set_status", seat=seat, status="away")
    if short_post:
        s.do("set_config", short_post=short_post)
    if remaining:
        s.do("set_tournament", remaining=remaining, paid=paid)
    if deal:
        s.do("deal")
    return s


def table_a(**kw):
    return new_table(**kw)


def play(s, script):
    """``"4 raise 500, 5 fold"``: one act intent per step, each for the seat named."""
    view = None
    for step in script.split(","):
        parts = step.split()
        view = s.do("act", seat=int(parts[0]), kind=parts[1], amount=parts[2] if len(parts) > 2 else None)
    return view


def state(s) -> HandState:
    return s.hand_state()


def stack(s, seat):
    """The stack as the table shows it: chips behind during a hand, the settled stack after it."""
    return [x for x in s.view()["table"]["seats"] if x["seat"] == seat][0]["stack"]


def pots(s):
    return [(p["amount"], p["eligible"]) for p in state(s).pots()]


def against_the_rules(s, seat, kind, to=None):
    """True when the strict machine refuses this event as the next one of the hand."""
    hand = copy.deepcopy(s.data["hand"])
    hand["events"].append({"street": replay(hand).phase, "seat": seat, "kind": kind, "to": to, "auto": False})
    try:
        replay(hand)
    except ModelError:
        return True
    return False


def refused(s, op, **args):
    """The error of an intent that must be refused; the session must be untouched."""
    before = json.dumps(s.data, sort_keys=True)
    try:
        s.do(op, **args)
    except ModelError as err:
        assert json.dumps(s.data, sort_keys=True) == before, "a refused intent changed the session"
        return err
    raise AssertionError(f"{op} {args} was accepted")


# --------------------------------------------------------------------------
# The engine fix: one table of seat names
# --------------------------------------------------------------------------

class SeatNames(unittest.TestCase):
    def test_the_table(self):
        self.assertEqual(SEAT_LABELS[2], ["BTN/SB", "BB"])
        self.assertEqual(SEAT_LABELS[6], ["LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(SEAT_LABELS[7], ["UTG", "LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(SEAT_LABELS[8], ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(SEAT_LABELS[9], ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB"])

    def test_every_module_agrees(self):
        for n in range(2, 10):
            names = [position_name(n - 1 - i, n) for i in range(n)]
            self.assertEqual(names, SEAT_LABELS[n])
            # every printed name is read back as its own seat
            self.assertEqual([pos_to_index(name, n) for name in names], list(range(n)), n)
            if n >= 3:
                self.assertEqual(names, [binary.seat_name(n - 1 - i, n) for i in range(n)])

    def test_other_spellings(self):
        self.assertEqual(pos_to_index("UTG+1", 8), 1)          # was seat 0 before the fix
        self.assertEqual(pos_to_index("button", 6), 3)
        self.assertEqual(pos_to_index("UTG", 6), 0)            # first to act, whatever it is called
        self.assertEqual(pos_to_index("UTG(LJ)", 6), 0)        # the old spelling still reads
        self.assertEqual(pos_to_index("SB/BTN", 2), 0)
        self.assertEqual(pos_to_index("SB", 2), 0)
        self.assertEqual(pos_to_index("MP", 9), 2)
        self.assertEqual(pos_to_index("UTG+1", 6), 1)          # no such seat six-handed: the second to act
        self.assertIsNone(pos_to_index("nowhere", 6))

    def test_model_labels(self):
        self.assertEqual(seat_labels([4, 5, 6, 1, 2, 3]), {4: "LJ", 5: "HJ", 6: "CO", 1: "BTN", 2: "SB", 3: "BB"})
        self.assertEqual(seat_labels([1, 2]), {1: "BTN/SB", 2: "BB"})
        self.assertEqual(seat_labels([3]), {})


# --------------------------------------------------------------------------
# The amount parser
# --------------------------------------------------------------------------

class Amounts(unittest.TestCase):
    def test_every_spelling(self):
        ctx = dict(bb=600, bet=1320, pot=4500, current=10000)
        for typed, value in [("1300", 1300), ("1,300", 1300), ("12.5k", 12500), ("1.2m", 1200000),
                             ("25bb", 15000), ("2.2b", 1320), ("3x", 3960), ("66%", 2970), ("+3k", 13000),
                             ("-1500", 8500), (" 12,5K ", 12500), ("2,2bb", 1320), ("1,300,000", 1300000),
                             ("$11", 11), (1300, 1300), (62.5, 63)]:
            self.assertEqual(parse_amount(typed, **ctx), value, typed)

    def test_big_blind_tables(self):
        self.assertEqual(parse_amount("8", bb=1, step=0.1), 8)
        self.assertEqual(parse_amount("5.5", bb=1, step=0.1), 5.5)
        self.assertEqual(parse_amount("2.5bb", bb=1, step=0.1), 2.5)

    def test_clear_errors(self):
        for typed, ctx in [("", {}), ("abc", {}), ("25bb", {}), ("3x", {"bb": 100}), ("3x", {"bet": 0}),
                           ("66%", {"bb": 100}), ("+3k", {"bb": 100}), ("-500", {"current": 200}),
                           ("1..2", {}), (-5, {}), (None, {})]:
            with self.assertRaises(AmountError, msg=typed) as caught:
                parse_amount(typed, **ctx)
            self.assertTrue(caught.exception.message and caught.exception.fix, typed)

    def test_blinds(self):
        self.assertEqual(parse_blinds("300/600/75"), {"sb": 300, "bb": 600, "ante": 75})
        self.assertEqual(parse_blinds("600"), {"sb": None, "bb": 600, "ante": None})
        self.assertEqual(parse_blinds("1k/2k"), {"sb": 1000, "bb": 2000, "ante": None})
        self.assertEqual(parse_blinds("300/600 a75"), {"sb": 300, "bb": 600, "ante": 75})
        self.assertEqual(parse_blinds("0.5/1"), {"sb": 0.5, "bb": 1, "ante": None})
        for bad in ("", "600/300", "1/2/3/4", "x/y", "0"):
            with self.assertRaises(AmountError, msg=bad):
                parse_blinds(bad)

    def test_ladder_and_payouts(self):
        ladder = parse_ladder("1: 100/200/25\nL2 150/300/40\n\n# a comment\n200/400\n600")
        self.assertEqual([(lv["sb"], lv["bb"], lv["ante"]) for lv in ladder],
                         [(100, 200, 25), (150, 300, 40), (200, 400, 0), (300, 600, 0)])
        with self.assertRaises(AmountError):
            parse_ladder("200/400\n100/200")
        with self.assertRaises(AmountError):
            parse_ladder("")
        self.assertEqual(parse_payouts("1:1000 2:600 4-6:200"), [1000, 600, 200, 200, 200, 200])
        self.assertEqual(parse_payouts("1,000 600 400"), [1000, 600, 400])
        self.assertIsNone(parse_payouts("auto"))
        with self.assertRaises(AmountError):
            parse_payouts("1:abc")

    def test_text(self):
        self.assertEqual(fmt(12900), "12,900")
        self.assertEqual(fmt(8.4), "8.4")
        self.assertEqual(fmt_bb(1320, 600), "2.2bb")
        self.assertEqual(fmt_bb(1800, 600), "3bb")


# --------------------------------------------------------------------------
# Cases 1 to 11: setup
# --------------------------------------------------------------------------

class Setup(unittest.TestCase):
    def test_01_deal(self):
        s = table_a()
        st = state(s)
        self.assertEqual(st.labels, {LJ: "LJ", HJ: "HJ", CO: "CO", BTN: "BTN", SB: "SB", BB: "BB"})
        self.assertEqual((st.pot_total(), st.to_act(), st.owe(LJ), st.min_raise_to(LJ)), (300, LJ, 200, 400))

    def test_02_button_moves_over_an_empty_seat(self):
        self.assertEqual(preflop_order([1, 2, 4, 5], 4), [2, 4, 5, 1])
        s = new_table(size=5, button=2, deal=False)
        s.do("clear_seat", seat=3)
        s.do("deal")                                    # the first hand is played where the button was put
        self.assertEqual(s.data["hand"]["button"], 2)
        s.do("close_round")                             # everybody folds: the hand is over
        view = s.do("deal")
        self.assertEqual(view["table"]["button"], 4)
        pos = {x["seat"]: x["pos"] for x in view["table"]["seats"] if not x["empty"]}
        self.assertEqual(pos, {2: "CO", 4: "BTN", 5: "SB", 1: "BB"})

    def test_03_heads_up(self):
        s = new_table(size=2, stack=3000, blinds="50/100/0", button=1)
        st = state(s)
        self.assertEqual(st.labels, {1: "BTN/SB", 2: "BB"})
        self.assertEqual((st.to_act(), st.owe(1), st.min_raise_to(1)), (1, 50, 200))
        play(s, "1 call, 2 check")
        st = state(s)
        self.assertEqual((st.phase, st.pot_total(), st.to_act()), ("flop", 200, 2))

    def test_04_heads_up_after_a_bust(self):
        s = new_table(size=3, blinds="100/200/0", button=1, stacks={2: 500})
        play(s, "1 fold, 2 allin, 3 call")
        view = s.do("award", winner=3)
        self.assertTrue([x for x in view["table"]["seats"] if x["seat"] == 2][0]["empty"])
        view = s.do("deal")
        pos = {x["seat"]: x["pos"] for x in view["table"]["seats"] if not x["empty"]}
        self.assertEqual(pos, {3: "BTN/SB", 1: "BB"})

    def test_05_antes(self):
        s = table_a(blinds="100/200/25")
        st = state(s)
        self.assertEqual(st.pot_total(), 450)
        self.assertEqual((st.stack[LJ], st.stack[SB], st.stack[BB]), (9975, 9875, 9775))

    def test_06_short_big_blind(self):
        s = table_a(stacks={BB: 120})
        st = state(s)
        self.assertEqual((st.owe(LJ), st.min_raise_to(LJ)), (200, 400))     # the full big blind is the bet
        play(s, "4 fold, 5 fold, 6 fold, 1 fold")
        st = state(s)
        self.assertEqual((st.to_act(), st.owe(SB)), (SB, 20))
        self.assertFalse(st.may_raise(SB))

    def test_07_short_big_blind_called(self):
        s = table_a(stacks={BB: 120})
        play(s, "4 call, 5 fold, 6 fold, 1 fold, 2 fold")
        st = state(s)
        self.assertEqual((st.phase, st.returned, st.pot_total()), ("showdown", {LJ: 80}, 340))
        s.do("award", winner=BB)
        self.assertEqual((stack(s, BB), stack(s, LJ)), (340, 9880))

    def test_08_all_in_on_the_ante(self):
        s = table_a(blinds="100/200/25", stacks={HJ: 20})
        play(s, "4 raise 500, 6 fold, 1 fold, 2 fold, 3 call")
        self.assertEqual(pots(s), [(120, [LJ, HJ, BB]), (1125, [LJ, BB])])

    def test_09_short_big_blind_with_a_big_blind_ante(self):
        s = table_a(bb_ante=True, stacks={BB: 300})
        st = state(s)
        self.assertEqual((st.dead, st.in_front[BB], st.pot_total()), (200, 100, 400))    # the ante first
        s = table_a(bb_ante=True, stacks={BB: 300}, short_post="blind_first")
        st = state(s)
        self.assertEqual((st.dead, st.in_front[BB], st.pot_total()), (100, 200, 400))    # the blind first

    def test_10_big_blind_all_in_for_the_ante(self):
        s = table_a(bb_ante=True, stacks={BB: 150})
        play(s, "4 fold, 5 fold, 6 fold, 1 fold")
        st = state(s)                                   # the small blind has nothing to decide
        self.assertEqual((st.phase, st.returned, st.pot_total()), ("showdown", {SB: 100}, 150))

    def test_11_ante_and_part_of_the_blind(self):
        s = table_a(blinds="100/200/25", stacks={BB: 100})
        play(s, "4 call, 5 fold, 6 fold, 1 fold, 2 fold")
        self.assertEqual(state(s).returned, {LJ: 100})
        self.assertEqual(pots(s), [(375, [LJ, BB]), (50, [LJ])])
        s.do("award", winner=BB)
        self.assertEqual((stack(s, BB), stack(s, LJ)), (375, 9925))


# --------------------------------------------------------------------------
# Cases 12 to 20: betting
# --------------------------------------------------------------------------

class Betting(unittest.TestCase):
    def test_12_raise_and_folds(self):
        s = table_a()
        play(s, "4 raise 500, 5 fold, 6 fold, 1 fold, 2 fold")
        st = state(s)
        self.assertEqual((st.pot_total(), st.owe(BB), st.min_raise_to(BB)), (800, 300, 800))
        view = play(s, "3 fold")
        self.assertEqual(view["hand"]["phase"], "done")             # no intent needed for the winner
        self.assertEqual(stack(s, LJ), 10300)

    def test_13_limped_pot(self):
        s = table_a()
        play(s, "4 call, 5 fold, 6 fold, 1 call, 2 call")
        st = state(s)
        self.assertEqual((st.to_act(), st.owe(BB), st.min_raise_to(BB)), (BB, 0, 400))
        play(s, "3 check")
        st = state(s)
        self.assertEqual((st.phase, st.pot_total(), st.to_act()), ("flop", 800, SB))

    def test_14_minimum_raises(self):
        s = table_a()
        play(s, "4 raise 500, 5 raise 1300")
        st = state(s)
        self.assertEqual((st.owe(CO), st.min_raise_to(CO)), (1300, 2100))
        self.assertTrue(against_the_rules(s, CO, "raise", 2000))
        play(s, "6 raise 2100")
        st = state(s)
        self.assertEqual((st.min_raise_to(BTN), st.pot_total()), (2900, 4200))

    def test_15_short_all_in_does_not_reopen(self):
        s = table_a(stacks={HJ: 700})
        play(s, "4 raise 500, 5 allin")
        st = state(s)
        self.assertEqual((st.owe(CO), st.min_raise_to(CO)), (700, 1000))
        play(s, "6 fold, 1 fold, 2 fold, 3 fold")
        st = state(s)
        self.assertEqual(st.owe(LJ), 200)
        self.assertFalse(st.may_raise(LJ))
        self.assertTrue(against_the_rules(s, LJ, "raise", 1500))
        play(s, "4 call")
        st = state(s)
        self.assertEqual((st.phase, st.pot_total()), ("showdown", 1700))

    def test_16_a_full_raise_reopens(self):
        s = table_a(stacks={HJ: 700})
        play(s, "4 raise 500, 5 allin, 6 raise 1000, 1 fold, 2 fold, 3 fold")
        st = state(s)
        self.assertEqual((st.owe(LJ), st.may_raise(LJ), st.min_raise_to(LJ)), (500, True, 1300))

    def test_17_short_all_ins_add_up(self):
        s = table_a(stacks={HJ: 700, CO: 850})
        play(s, "4 raise 500, 5 allin, 6 allin, 1 call, 2 fold, 3 fold")
        st = state(s)
        self.assertEqual((st.owe(LJ), st.may_raise(LJ), st.min_raise_to(LJ)), (350, True, 1150))
        play(s, "4 call")
        self.assertEqual([amount for amount, _ in pots(s)], [3100, 450])

    def test_18_what_the_rules_refuse(self):
        s = table_a(stacks={LJ: 300})
        self.assertTrue(against_the_rules(s, LJ, "raise", 500))     # more than his stack
        self.assertTrue(against_the_rules(s, HJ, "fold"))           # out of turn
        self.assertTrue(against_the_rules(s, LJ, "check"))          # facing the big blind
        play(s, "4 allin")
        st = state(s)
        self.assertEqual((st.owe(HJ), st.min_raise_to(HJ)), (300, 500))

    def test_19_all_in_below_the_big_blind(self):
        s = table_a(stacks={LJ: 150})
        play(s, "4 allin, 5 fold, 6 fold, 1 fold, 2 fold")
        st = state(s)                                   # the big blind has nothing to decide
        self.assertEqual((st.phase, st.returned, st.pot_total()), ("showdown", {BB: 50}, 400))

    def test_20_check_raise_after_the_flop(self):
        s = table_a()
        play(s, "4 raise 500, 5 fold, 6 fold, 1 call, 2 fold, 3 call, 3 check, 4 bet 600, 1 call")
        self.assertEqual(state(s).min_raise_to(BB), 1200)
        self.assertTrue(against_the_rules(s, BB, "raise", 1000))
        play(s, "3 raise 1200, 4 fold, 1 call")
        st = state(s)
        self.assertEqual((st.phase, st.pot_total()), ("turn", 4600))


# --------------------------------------------------------------------------
# Cases 21 to 30: pots and results
# --------------------------------------------------------------------------

class PotsAndResults(unittest.TestCase):
    def side_pot(self):
        """Case 21: the button all-in for 3,000, a side pot of 4,000 between LJ and BB."""
        s = table_a(stacks={BTN: 3000})
        play(s, "4 raise 500, 5 fold, 6 fold, 1 allin, 2 fold, 3 call, 4 call")
        self.assertEqual(state(s).pot_total(), 9100)
        play(s, "3 check, 4 bet 2000, 3 call, 3 check, 4 check, 3 check, 4 check")
        return s

    def test_21_main_and_side_pot(self):
        s = self.side_pot()
        self.assertEqual(state(s).phase, "showdown")
        self.assertEqual([amount for amount, _ in pots(s)], [9100, 4000])

    def test_22_different_winners(self):
        s = self.side_pot()
        s.do("award", ranking=[[BTN], [LJ]])
        self.assertEqual((stack(s, BTN), stack(s, LJ), stack(s, BB)), (9100, 9000, 5000))
        s = self.side_pot()
        view = s.do("award", ranking=[[BB]])
        self.assertEqual(stack(s, BB), 18100)
        self.assertEqual(view["hand"]["result"]["busted"], [BTN])

    def test_23_every_pot_needs_a_winner(self):
        s = self.side_pot()
        err = refused(s, "award", ranking=[[BTN]])
        self.assertIn("side pot of 4,000", err.message)             # the error names the pot
        s.do("award", ranking=[[BTN, LJ], [BB]])
        self.assertEqual((stack(s, BTN), stack(s, LJ)), (4550, 13550))

    def test_24_uncalled_part_of_an_all_in(self):
        s = table_a(stacks={BB: 3000})
        play(s, "4 fold, 5 fold, 6 fold, 1 fold, 2 allin")
        self.assertEqual(state(s).owe(BB), 2800)
        play(s, "3 call")
        st = state(s)
        self.assertEqual((st.returned, st.pot_total(), st.phase), ({SB: 7000}, 6000, "showdown"))
        refused(s, "act", seat=BB, kind="bet", amount=500)
        s.do("award", winner=BB)
        self.assertEqual((stack(s, BB), stack(s, SB)), (6000, 7000))

    def three_all_ins(self):
        s = table_a(stacks={LJ: 1000, HJ: 2500, CO: 6000}, remaining=96, paid=20)
        play(s, "4 allin, 5 allin, 6 allin, 1 fold, 2 fold, 3 fold")
        return s

    def test_25_three_all_ins(self):
        s = self.three_all_ins()
        self.assertEqual(state(s).returned, {CO: 3500})
        self.assertEqual([amount for amount, _ in pots(s)], [3300, 3000])
        s.do("award", ranking=[[LJ], [HJ], [CO]])
        self.assertEqual((stack(s, LJ), stack(s, HJ), stack(s, CO)), (3300, 3000, 3500))

    def test_26_busts_lower_players_left(self):
        s = self.three_all_ins()
        view = s.do("award", ranking=[[CO]])
        self.assertEqual(stack(s, CO), 9800)
        self.assertEqual(view["hand"]["result"]["busted"], [LJ, HJ])
        self.assertEqual(view["strip"]["remaining"], 94)
        s = self.three_all_ins()
        s.do("award", ranking=[[LJ, HJ], [CO]])
        self.assertEqual((stack(s, LJ), stack(s, HJ)), (1650, 4650))

    def test_27_odd_chip(self):
        s = new_table(size=3, blinds="25/50/0", button=1)
        play(s, "1 raise 125, 2 fold, 3 call, 3 check, 1 check, 3 check, 1 check, 3 check, 1 check")
        self.assertEqual(state(s).pot_total(), 275)
        s.do("award", winners=[1, 3])
        self.assertEqual((stack(s, 3) - 9875, stack(s, 1) - 9875), (138, 137))     # the big blind is left of the button

    def test_28_short_small_blind_wins_only_his_pot(self):
        s = table_a(stacks={SB: 60})
        play(s, "4 raise 500, 5 fold, 6 fold, 1 fold, 3 call, 3 check, 4 bet 600, 3 fold")
        st = state(s)
        self.assertEqual((st.phase, st.returned), ("showdown", {LJ: 600}))
        self.assertEqual(pots(s), [(180, [LJ, SB]), (880, [LJ])])
        s.do("award", winner=SB)
        self.assertEqual((stack(s, SB), stack(s, LJ)), (180, 10380))

    def test_29_side_betting_after_an_all_in(self):
        s = table_a(stacks={LJ: 2000})
        play(s, "4 raise 500, 5 fold, 6 fold, 1 call, 2 fold, 3 call, 3 check, 4 allin, 1 call, 3 call")
        st = state(s)
        self.assertEqual((st.phase, st.pot_total(), st.to_act()), ("turn", 6100, BB))
        play(s, "3 bet 1000, 1 fold")
        st = state(s)
        self.assertEqual((st.returned, st.phase), ({BB: 1000}, "showdown"))

    def test_30_steal_with_a_big_blind_ante(self):
        s = table_a(bb_ante=True)
        play(s, "4 fold, 5 fold, 6 fold, 1 raise 450, 2 fold, 3 fold")
        self.assertEqual(stack(s, BTN), 10500)


# --------------------------------------------------------------------------
# Case 31: random hands
# --------------------------------------------------------------------------

def random_action(rng, st: HandState, seat):
    """One legal event for the player to act, chosen like the reference fuzzer does."""
    owe = st.owe(seat)
    options = ["fold"] if owe > 0 else ["check"]
    if owe > 0:
        options += ["call", "call"]
    if st.may_raise(seat):
        options += ["raise", "allin"]
    elif owe > 0:
        options += ["allin"]
    kind = rng.choice(options)
    event = {"street": st.phase, "seat": seat, "kind": kind, "auto": False}
    if kind == "raise":
        low, high = st.min_raise_to(seat), st.max_to(seat)
        event["to"] = rng.randint(low, high) if high > low else high
        event["kind"] = "bet" if st.bet_to == 0 else "raise"
    return event


class RandomHands(unittest.TestCase):
    def test_31_chips_are_conserved_and_the_hand_always_goes_on(self):
        rng = random.Random(7)
        for _ in range(4000):
            n = rng.randint(2, 9)
            bb = rng.choice([20, 100, 200, 2000])
            stacks = {seat: rng.choice([1, bb // 2, bb, bb + 5, 3 * bb, 12 * bb, 40 * bb, 100 * bb])
                      for seat in range(1, n + 1)}
            kind = rng.choice(["none", "player", "bb"])
            level = {"sb": bb // 2, "bb": bb, "ante": bb // 8 if kind == "player" else 0,
                     "bb_ante": bb if kind == "bb" else 0}
            hand = build_hand(1, stacks, rng.randint(1, n), level,
                              away=[seat for seat in stacks if rng.random() < 0.1],
                              rules={"short_post": rng.choice(["ante_first", "blind_first"]),
                                     "allin_or_fold": False, "fee": 0})
            total = sum(stacks.values())
            st = HandState(hand)
            steps = 0
            while st.phase in BETTING:
                seat = st.to_act()
                self.assertIsNotNone(seat, "the hand is open and nobody is to act")
                self.assertEqual(sum(st.stack.values()) + st.pot_total(), total)
                event = random_action(rng, st, seat)
                st.apply(event)
                hand["events"].append(event)
                steps += 1
                self.assertLess(steps, 500)
            self.assertIn(st.phase, ("showdown", "done"))
            if st.phase == "showdown":
                self.assertEqual(sum(st.stack.values()) + st.pot_total(), total)
                self.assertEqual(sum(p["amount"] for p in st.pots()), st.pot_total())
                live = st.live()
                rng.shuffle(live)
                hand["ranking"] = [[seat] for seat in live]
                st.award(hand["ranking"])
            self.assertEqual(sum(st.stack.values()), total)
            self.assertEqual(sum(p["amount"] for p in st.result["pots"]), sum(st.result["won"].values()))
            again = replay(hand)                        # the stored hand replays to the same place
            self.assertEqual((again.phase, again.stack, len(again.log)), ("done", st.stack, len(st.log)))

    def test_all_in_or_fold_hands(self):
        rng = random.Random(8)
        level = {"sb": 0.5, "bb": 1, "ante": 0, "bb_ante": 0}
        for _ in range(1500):
            n = rng.randint(2, 4)
            stacks = {seat: rng.choice([0.4, 1, 2.5, 5.5, 8, 8, 8]) for seat in range(1, n + 1)}
            hand = build_hand(1, stacks, rng.randint(1, n), level,
                              rules={"short_post": "ante_first", "allin_or_fold": True, "fee": 0.1})
            total = sum(stacks.values())
            st = HandState(hand)
            while st.phase in BETTING:
                seat = st.to_act()
                self.assertIsNotNone(seat)
                event = {"street": "preflop", "seat": seat, "kind": rng.choice(["fold", "allin"]), "auto": False}
                st.apply(event)
                hand["events"].append(event)
            self.assertNotIn(st.phase, ("flop", "turn", "river"))   # there is no betting after the flop
            if st.phase == "showdown":
                live = st.live()
                rng.shuffle(live)
                st.award([[seat] for seat in live])
            self.assertAlmostEqual(sum(st.stack.values()) + st.result["fee"], total, places=6)

    def test_random_intents_never_break_the_session(self):
        """Whatever is typed, the answer is a view or a plain refusal, and the chips of the hand add up."""
        rng = random.Random(9)
        amounts = [None, "2.2bb", "3x", "50%", "66%", 150, 400, 1000, 5000, "12k", "0", "abc", "+200", 99999]
        cards = ["AhKd", "AKs", "77", "Ks7d2c", "9h", "Td", "QsQh", "zz", "AhAh", "2c3c4c5c6c"]
        ops = ["deal", "act", "act", "act", "act", "act", "act", "close_round", "set_cards", "award", "undo",
               "redo", "set_stack", "edit_event", "remove_event", "button_step", "level_up", "level_down",
               "set_status", "bust", "clear_seat", "seat_player", "skip_hand", "discard_hand", "set_ante_kind",
               "new_game", "set_stacks", "set_level", "new_table", "remaining", "set_tournament", "set_config",
               "set_type", "rename", "note", "set_button", "set_size", "set_ladder", "new_session"]
        rare = ("bust", "clear_seat", "new_table", "new_game", "set_stacks", "new_session", "set_size", "set_ladder")
        for mode in D.MODES:
            s = Session(save=False)
            s.do("set_mode", mode=mode)
            accepted = hands = 0
            for _ in range(2500):
                size = s.data["table"]["size"]
                seat = rng.randint(1, size)
                op = rng.choice(ops)
                if s.data["hand"] is None or s.data["hand"]["settled"]:
                    op = "deal" if rng.random() < 0.75 else op      # keep hands coming
                args = {
                    "act": {"seat": rng.choice([None, seat]), "amount": rng.choice(amounts),
                            "kind": rng.choice(["fold", "check", "call", "bet", "raise", "allin"])},
                    "close_round": {"callers": rng.sample(range(1, size + 1), rng.randint(0, 2))},
                    "set_cards": {"slot": rng.choice(["hero", "board", "flop", "turn", "river", ""]),
                                  "text": rng.choice(cards)},
                    "award": rng.choice([{"winner": seat}, {"hero": "won"}, {"hero": "lost"}, {"split": True},
                                         {"ranking": [[seat], [rng.randint(1, size)]]}, {}]),
                    "set_stack": {"seat": seat, "text": rng.choice(amounts[1:])},
                    "edit_event": {"index": rng.randint(0, 8), "amount": rng.choice(amounts),
                                   "kind": rng.choice([None, "call", "raise", "fold"])},
                    "remove_event": {"index": rng.randint(0, 8)},
                    "button_step": {"step": rng.choice([-1, 1])},
                    "set_status": {"seat": seat}, "bust": {"seat": seat}, "clear_seat": {"seat": seat},
                    "seat_player": {"seat": seat, "stack": rng.choice([None, 3000, "20bb"])},
                    "set_stacks": {"values": [rng.choice(["", "-", 5000, "8"]) for _ in range(size)]},
                    "set_level": {"text": rng.choice(["300/600/75", "600", "50/100", "bad"])},
                    "remaining": {"delta": rng.choice([-1, 1])},
                    "set_tournament": rng.choice([{"remaining": 96, "paid": 75}, {"entrants": 500},
                                                  {"avg_stack": "30bb"}, {"payouts": "1:100 2:50"},
                                                  {"remaining": ""}, {"field": "paid", "text": "x"}]),
                    "set_config": rng.choice([{"style": "cash"}, {"plan": "allin"}, {"unit": "bb"},
                                              {"opponents": "loose"}, {"reentry_open": True}, {"key": "deck"}]),
                    "set_type": {"seat": seat, "type": rng.choice(["nit", "lag", "x", "s"])},
                    "rename": {"seat": seat, "name": rng.choice(["Hal", "", "Zoe"])},
                    "note": {"seat": seat, "text": "limps a lot"},
                    "set_button": {"seat": seat},
                    "set_size": {"delta": rng.choice([-1, 1])},
                    "set_ladder": rng.choice([{"name": "regular"}, {"name": "turbo"},
                                              {"text": "100/200\n200/400/50"}, {"name": "zzz"}]),
                    "new_session": rng.choice([{}, {"size": 6}, {"start_stack": "5k"}]),
                }.get(op, {})
                if op in rare and rng.random() < 0.85:
                    continue                            # keep the table mostly as it is
                try:
                    view = s.do(op, **args)
                except ModelError as err:
                    self.assertTrue(err.message)
                    self.assertNotIn("could not be read", err.message, (op, args))    # that would be a bug inside
                    continue
                accepted += 1
                hands += op == "deal"
                hand = s.data["hand"]
                if hand and not hand["settled"]:
                    st = replay(hand)
                    self.assertAlmostEqual(sum(st.stack.values()) + st.pot_total(), sum(st.start.values()), places=6)
                    self.assertIn(st.phase, BETTING + ("showdown",))
                    self.assertEqual(view["hand"]["target"] is not None, st.phase in BETTING)
                json.dumps(view)                        # the view is plain JSON
            self.assertGreater(accepted, 1000, mode)
            self.assertGreater(hands, 150, mode)


# --------------------------------------------------------------------------
# Cases 32 to 37: edits during a hand
# --------------------------------------------------------------------------

class Edits(unittest.TestCase):
    def test_32_a_player_sitting_out(self):
        s = table_a(away=[BB])
        view = play(s, "4 fold, 5 fold, 6 fold, 1 raise 400, 2 fold")
        self.assertEqual(view["hand"]["phase"], "done")             # the big blind folded by itself
        self.assertEqual(stack(s, BTN), 10300)
        s = table_a(away=[BB])
        view = play(s, "4 fold, 5 fold, 6 fold, 1 fold, 2 call")
        self.assertEqual(view["hand"]["phase"], "flop")             # ... and here it checked by itself
        last = view["hand"]["line"][-1]
        self.assertEqual((last["seat"], last["verb"], last["auto"]), (BB, "check", True))

    def test_33_a_seat_cleared_during_the_hand(self):
        s = table_a()
        play(s, "4 raise 500, 5 fold, 6 call")
        s.do("clear_seat", seat=CO)
        self.assertEqual(state(s).pot_total(), 1300)                # his chips stay in the pot
        self.assertFalse([x for x in s.view()["table"]["seats"] if x["seat"] == CO][0]["empty"])
        play(s, "1 call, 2 fold, 3 fold")
        st = state(s)
        self.assertEqual(st.phase, "flop")
        play(s, "4 bet 600")
        self.assertIn(CO, state(s).folded)                          # he folded at his turn, without being told
        view = play(s, "1 fold")
        self.assertEqual(view["hand"]["phase"], "done")
        self.assertTrue([x for x in view["table"]["seats"] if x["seat"] == CO][0]["empty"])

    def test_34_blinds_changed_during_the_hand(self):
        s = table_a(blinds="100/200/25")
        view = s.do("level_up")                         # nobody has acted: the hand is posted again
        self.assertEqual(view["strip"]["level"]["bb"], 300)
        self.assertEqual(state(s).pot_total(), 150 + 300 + 6 * 40)
        self.assertIsNone(view["strip"]["level"]["pending"])
        play(s, "4 call")
        view = s.do("level_up")                         # after the first action: the next hand gets them
        self.assertEqual(view["strip"]["level"]["bb"], 300)
        self.assertEqual(view["strip"]["level"]["pending"]["bb"], 400)
        self.assertEqual(state(s).bb, 300)
        s.do("close_round")
        view = s.do("deal")
        self.assertEqual((view["strip"]["level"]["bb"], view["strip"]["level"]["pending"]), (400, None))

    def test_35_undo_and_redo_a_result(self):
        s = PotsAndResults().three_all_ins()
        s.do("award", ranking=[[CO]])
        view = s.do("undo")
        self.assertEqual(view["hand"]["phase"], "showdown")
        self.assertEqual([p["amount"] for p in view["hand"]["pots"]], [3300, 3000])
        self.assertEqual(view["strip"]["remaining"], 96)
        self.assertEqual(view["history"], [])
        self.assertFalse([x for x in view["table"]["seats"] if x["seat"] == LJ][0]["empty"])
        view = s.do("redo")
        self.assertEqual((view["hand"]["phase"], view["strip"]["remaining"]), ("done", 94))
        self.assertEqual(stack(s, CO), 9800)
        self.assertEqual(len(view["history"]), 1)

    def test_36_editing_an_earlier_raise(self):
        s = table_a()
        play(s, "4 raise 500, 5 raise 1300, 6 raise 2100")
        hj = [item["i"] for item in s.view()["hand"]["line"] if item.get("seat") == HJ][0]
        view = s.do("edit_event", index=hj, amount=900)
        self.assertEqual([(i["seat"], i["to"]) for i in view["hand"]["line"]], [(LJ, 500), (HJ, 900), (CO, 2100)])
        self.assertIsNone(view["toast"])
        view = s.do("edit_event", index=hj, amount=1900)    # now 2,100 is less than a minimum raise
        self.assertEqual([(i["seat"], i["to"]) for i in view["hand"]["line"]], [(LJ, 500), (HJ, 1900)])
        self.assertIn("dropped", view["toast"]["text"])
        self.assertIn("2,100", view["toast"]["text"])
        self.assertEqual(state(s).to_act(), CO)         # he is to act again

    def test_37_a_hand_left_without_its_result(self):
        # Table A turned so that hero (seat 1) is the cutoff: the button is on seat 2
        s = new_table(button=2)
        lj, hj = 5, 6
        self.assertEqual(state(s).labels[HERO], "CO")
        play(s, f"{lj} raise 500, {hj} fold, 1 fold")
        view = s.do("skip_hand")
        self.assertIsNone(view["hand"])
        seats = {x["seat"]: x for x in view["table"]["seats"]}
        self.assertEqual([seats[n]["stale"] for n in (1, hj)], [False, False])          # they folded: exact
        self.assertEqual([seats[n]["stale"] for n in (lj, 2, 3, 4)], [True] * 4)        # still in: unsure
        self.assertEqual([seats[n]["stack"] for n in range(1, 7)], [10000] * 6)
        self.assertEqual(view["table"]["button"], 3)                                    # the button moved on
        self.assertTrue(view["history"][0]["skipped"])
        self.assertEqual(view["history"][0]["net"], 0)

    def test_a_stack_corrected_during_the_hand(self):
        s = table_a()
        play(s, "4 raise 500, 5 fold, 6 fold")
        s.do("set_stack", seat=LJ, text="7500")         # the chips he has behind now
        st = state(s)
        self.assertEqual((st.start[LJ], st.stack[LJ], st.in_front[LJ]), (8000, 7500, 500))
        s.do("discard_hand")
        self.assertEqual(stack(s, LJ), 8000)

    def test_button_corrected_during_the_hand(self):
        s = table_a()
        s.do("set_cards", hero="AKs")
        play(s, "4 raise 500")
        view = s.do("button_step", step=-1)             # the button is really on seat 6
        self.assertEqual(view["table"]["button"], 6)
        st = state(s)
        self.assertEqual((st.labels[HERO], st.labels[4]), ("SB", "HJ"))
        self.assertEqual([(e["seat"], e["kind"], e["to"], e["auto"]) for e in st.log],
                         [(3, "fold", 0, True), (4, "raise", 500, False)])      # the raise stayed with its seat
        self.assertEqual(st.pot_total(), 800)
        self.assertEqual(view["hand"]["hero_class"], "AKs")
        view = s.do("button_step", step=1)
        view = s.do("button_step", step=1)              # on seat 2 the raiser would be the big blind
        self.assertIn("dropped", view["toast"]["text"])

    def test_remove_event_goes_back_to_the_default(self):
        s = table_a()
        play(s, "4 raise 500, 6 call")
        line = s.view()["hand"]["line"]
        err = refused(s, "remove_event", index=[i["i"] for i in line if i["auto"]][0])
        self.assertIn("not typed", err.message)
        view = s.do("remove_event", index=[i["i"] for i in line if i.get("seat") == CO][0])
        self.assertEqual([(i["seat"], i["verb"]) for i in view["hand"]["line"]], [(LJ, "raise")])


# --------------------------------------------------------------------------
# Ruling 3: friendly on top of strict
# --------------------------------------------------------------------------

class Friendly(unittest.TestCase):
    def test_skipped_players_take_the_passive_default(self):
        s = table_a()
        view = s.do("act", seat=CO, kind="raise", amount="2.5bb")
        self.assertEqual([(i["seat"], i["verb"], i["auto"]) for i in view["hand"]["line"]],
                         [(LJ, "fold", True), (HJ, "fold", True), (CO, "raise", False)])
        self.assertEqual(view["hand"]["line"][-1]["text"], "CO raise 2.5bb")
        s = table_a()
        play(s, "4 call")
        view = s.do("act", seat=BB, kind="raise", amount=1000)      # the small blind owed chips: he folded
        self.assertEqual([i["verb"] for i in view["hand"]["line"]][1:], ["fold", "fold", "fold", "fold", "raise"])

    def test_the_target_is_hero_when_he_owes_a_decision(self):
        s = table_a()
        view = s.view()
        self.assertEqual((view["hand"]["target"], view["hand"]["target_is_hero"]), (HERO, True))
        self.assertEqual(view["hand"]["to_call"], 200)
        view = s.do("act", seat=LJ, kind="raise", amount=500)
        self.assertEqual((view["hand"]["target"], view["hand"]["to_call"]), (HERO, 500))
        self.assertEqual(view["hand"]["legal"]["raise"], {"min": 800, "max": 10000, "default": 1500})
        view = s.do("act", kind="call")                 # no seat: the target acts
        self.assertEqual(view["hand"]["line"][-1]["seat"], HERO)
        self.assertEqual(view["hand"]["target"], SB)    # now the next player to act

    def test_hero_in_the_big_blind_gets_no_turn_when_everybody_folds(self):
        s = new_table(button=5)                         # seat 6 small blind, hero big blind
        view = s.view()
        self.assertEqual(state(s).labels[HERO], "BB")
        self.assertEqual(view["hand"]["target"], 2)     # folded round to him there is nothing to decide
        view = s.do("close_round")
        self.assertEqual((view["hand"]["phase"], stack(s, HERO)), ("done", 10100))

    def test_convert_do_not_reject(self):
        s = table_a()
        view = s.do("act", seat=LJ, kind="raise", amount=99999)     # above the stack: all-in
        self.assertEqual((view["hand"]["line"][-1]["verb"], view["hand"]["line"][-1]["to"]), ("allin", 10000))
        s = table_a()
        view = s.do("act", seat=LJ, kind="raise", amount=300)       # below the minimum: lifted to it
        self.assertEqual(view["hand"]["line"][-1]["to"], 400)
        self.assertIn("minimum", view["toast"]["text"])
        s = table_a()
        view = s.do("act", seat=LJ, kind="raise", amount=300, force=True)   # the screen wins when asked
        self.assertEqual(view["hand"]["line"][-1]["to"], 300)
        s = table_a()
        play(s, "4 call, 5 fold, 6 fold, 1 fold, 2 call")
        view = s.do("act", seat=BB, kind="call")                    # nothing to call: a check
        self.assertEqual(view["hand"]["line"][-1]["verb"], "check")
        view = s.do("act", seat=SB, kind="raise", amount=400)       # nobody has bet: a bet
        self.assertEqual(view["hand"]["line"][-1]["verb"], "bet")
        view = s.do("act", seat=BB, kind="bet", amount=1200)        # there is a bet: a raise
        self.assertEqual(view["hand"]["line"][-1]["verb"], "raise")

    def test_default_sizes(self):
        s = table_a()
        view = s.do("act", seat=LJ, kind="raise")                   # 2.2 big blinds to open
        self.assertEqual(view["hand"]["line"][-1]["to"], 440)
        view = s.do("act", seat=HJ, kind="raise")                   # three times the raise
        self.assertEqual(view["hand"]["line"][-1]["to"], 1320)
        play(s, "6 fold, 1 fold, 2 fold, 3 fold, 4 call")
        view = s.do("act", seat=LJ, kind="bet")                     # half the pot
        self.assertEqual(view["hand"]["line"][-1]["to"], (300 + 1320 * 2) // 2)

    def test_a_raise_where_none_is_possible_is_a_call(self):
        s = table_a(stacks={HJ: 700})
        play(s, "4 raise 500, 5 allin, 6 fold, 1 fold, 2 fold, 3 fold")
        view = s.do("act", seat=LJ, kind="raise", amount=1500)
        self.assertEqual(view["hand"]["line"][-1]["verb"], "call")
        self.assertIn("cannot raise", view["toast"]["text"])

    def test_a_caller_forgotten_in_front(self):
        s = table_a()
        s.do("act", seat=CO, kind="raise", amount=500)              # LJ and HJ fold by default
        view = s.do("act", seat=HJ, kind="call")                    # no: HJ had limped
        self.assertEqual([(i["seat"], i["verb"], i["auto"]) for i in view["hand"]["line"]],
                         [(LJ, "fold", True), (HJ, "call", False), (CO, "raise", False)])
        self.assertEqual(state(s).pot_total(), 300 + 200 + 500)

    def test_only_the_impossible_is_refused(self):
        s = table_a()
        s.do("clear_seat", seat=5)
        s.do("act", seat=LJ, kind="raise", amount=500)
        s.do("seat_player", seat=5, stack=8000)                     # sits down during the hand
        err = refused(s, "act", seat=5, kind="call")
        self.assertIn("not in this hand", err.message)
        play(s, "6 fold")
        self.assertIn("folded", refused(s, "act", seat=CO, kind="call").message)
        self.assertIn("cannot check", refused(s, "act", seat=BTN, kind="check").message)
        refused(s, "act", seat=9, kind="call")
        refused(s, "act", seat=BTN, kind="dance")
        refused(s, "act", seat=BTN, kind="raise", amount="lots")
        play(s, "1 allin")
        self.assertIn("all-in", refused(s, "act", seat=BTN, kind="call").message)
        for err in (refused(s, "nonsense"), refused(s, "award", winner=BTN)):
            self.assertTrue(err.message)

    def test_duplicate_cards_are_refused(self):
        s = table_a()
        s.do("set_cards", hero="AhKd")
        play(s, "4 call, 1 call")
        self.assertIn("The Ah is used twice", refused(s, "set_cards", board="AhKs2c").message)
        refused(s, "set_cards", board="KsKs2c")
        refused(s, "set_cards", hero="AxKd")
        refused(s, "set_cards", hero="AhAh")
        s.do("set_cards", board="Ks7d2c")
        self.assertIn("twice", refused(s, "set_cards", shown={LJ: "Ks9s"}).message)

    def test_typing_the_flop_closes_the_round(self):
        s = table_a()
        s.do("set_cards", hero="AhKd")
        play(s, "4 raise 500, 1 call")
        view = s.do("set_cards", board="Ks7d2c")        # the blinds were not mentioned: they folded
        self.assertEqual((view["hand"]["phase"], view["hand"]["board"]), ("flop", ["Ks", "7d", "2c"]))
        self.assertEqual(view["hand"]["pot"], 1300)
        view = s.do("set_cards", slot="turn", text="9h")
        self.assertEqual((view["hand"]["phase"], view["hand"]["board"][-1]), ("turn", "9h"))
        s = table_a()
        play(s, "4 raise 500")
        err = refused(s, "set_cards", board="Ks7d2c")   # nobody called: there is no flop
        self.assertIn("nobody called", err.message)

    def test_acting_behind_hero_folds_him(self):
        s = table_a()
        s.do("set_cards", hero="72o")
        s.record_advice(s.rev, "FOLD")
        view = s.do("act", seat=SB, kind="raise", amount=600)       # hero (button) was passed by: he folded
        self.assertEqual([(i["seat"], i["verb"], i["auto"]) for i in view["hand"]["line"] if i.get("seat") == HERO],
                         [(HERO, "fold", True)])
        view = s.do("close_round")
        entry = view["history"][0]
        self.assertEqual((entry["advice"], entry["did"], entry["deviated"], entry["net"]), ("FOLD", "fold", False, 0))
        self.assertIn("You fold", entry["text"])

    def test_what_counts_as_following_the_coach(self):
        for verb, follow, did, all_in, deviated in [
                ("RAISE", None, "raise", False, False), ("RAISE", None, "bet", False, False),
                ("RAISE", None, "call", False, True), ("ALL-IN", None, "raise", True, False),
                ("ALL-IN", None, "call", True, False), ("ALL-IN", None, "raise", False, True),
                ("RE-RAISE ALL-IN", None, "raise", True, False), ("CALL", None, "fold", False, True),
                ("RAISE to 2.0bb and call any all-in", None, "raise", False, False),
                ("3-BET", None, "raise", False, False), ("NO ADVICE", None, "fold", False, False),
                ("whatever", {"kind": "bet", "to": 300}, "bet", False, False),
                ("whatever", {"kind": "fold"}, "call", False, True), (None, None, "call", False, False)]:
            self.assertEqual(_deviated(verb, follow, did, all_in), deviated, (verb, follow, did, all_in))

    def test_pots_while_bets_are_open(self):
        s = table_a(stacks={HJ: 700})
        view = play(s, "4 raise 500")
        self.assertEqual(view["hand"]["pots"], [{"amount": 800, "eligible": [LJ, HJ, CO, BTN, SB, BB]}])
        view = play(s, "5 allin, 6 call")               # an all-in cuts the pot; the others can still match more
        self.assertEqual(view["hand"]["pots"], [{"amount": 300 + 500 + 700 + 700, "eligible": [LJ, HJ, CO, BTN, SB, BB]}])
        view = play(s, "1 raise 2000")
        self.assertEqual(view["hand"]["pots"][0]["eligible"], [LJ, HJ, CO, BTN, SB, BB])
        self.assertEqual(view["hand"]["pots"][1]["eligible"], [LJ, CO, BTN, SB, BB])
        self.assertEqual(sum(p["amount"] for p in view["hand"]["pots"]), view["hand"]["pot"])

    def test_deal_closes_a_hand_left_open(self):
        s = table_a()
        s.do("set_cards", hero="72o")
        view = s.do("deal")                             # "n 7 2 o n": hero folded
        self.assertEqual((view["hand"]["no"], view["history"][0]["did"]), (2, "fold"))
        self.assertEqual(view["history"][0]["net"], 0)
        self.assertEqual(view["table"]["button"], 2)    # the button moved on: hero is the cutoff now
        self.assertEqual(view["table"]["seats"][0]["pos"], "CO")


# --------------------------------------------------------------------------
# Cases 38 to 41: Spin
# --------------------------------------------------------------------------

def spin(stacks=None, blinds=None, button=1):
    s = Session(save=False)
    s.do("set_mode", mode="spin")
    s.do("new_session", button=button)
    if blinds:
        s.do("set_level", text=blinds)
    for seat, chips in (stacks or {}).items():
        s.do("set_stack", seat=seat, text=chips)
    s.do("deal")
    return s


class Spin(unittest.TestCase):
    def test_defaults(self):
        view = spin().view()
        self.assertEqual((view["mode"], view["table"]["size"], view["unit"]), ("spin", 3, "chips"))
        self.assertEqual([x["stack"] + x["bet"] for x in view["table"]["seats"]], [300, 300, 300])
        level = view["strip"]["level"]
        self.assertEqual((level["sb"], level["bb"], level["ante"], level["ante_kind"]), (10, 20, 0, "none"))
        self.assertEqual(view["strip"]["tally"], {"games": 0, "wins": 0})
        self.assertEqual((view["strip"]["icm"], view["strip"]["stage"]["code"]), ("off", "unknown"))

    def test_38_a_bust_makes_it_heads_up(self):
        s = spin()
        play(s, "1 allin, 2 fold, 3 call")
        view = s.do("award", winner=1)
        self.assertEqual(stack(s, 1), 610)
        self.assertEqual(view["hand"]["result"]["busted"], [3])
        self.assertEqual(view["strip"]["tally"], {"games": 0, "wins": 0})       # the game goes on
        view = s.do("deal")
        self.assertEqual({x["seat"]: x["pos"] for x in view["table"]["seats"] if not x["empty"]},
                         {2: "BTN/SB", 1: "BB"})

    def test_39_the_last_chip_ends_the_game(self):
        s = spin(stacks={1: 620, 2: 280}, blinds="15/30", button=2)
        s.do("clear_seat", seat=3)
        self.assertEqual(state(s).labels, {2: "BTN/SB", 1: "BB"})
        play(s, "2 allin, 1 call")
        view = s.do("award", hero="won")
        self.assertEqual(stack(s, 1), 900)
        self.assertEqual(view["strip"]["tally"], {"games": 1, "wins": 1})
        self.assertEqual(view["strip"]["game"]["over"], "won")
        view = s.do("deal")                             # the next deal starts a new game
        self.assertEqual([x["stack"] + x["bet"] for x in view["table"]["seats"]], [300, 300, 300])
        self.assertEqual(view["strip"]["level"]["bb"], 20)
        self.assertEqual(view["strip"]["tally"], {"games": 1, "wins": 1})

    def test_40_limp_all_in_fold(self):
        s = spin()
        play(s, "1 fold, 2 call, 3 allin")
        log = [(e["seat"], e["kind"]) for e in state(s).log]
        self.assertEqual(log, [(1, "fold"), (2, "call"), (3, "raise")])     # the big blind faced a limp
        self.assertEqual(state(s).owe(2), 280)
        play(s, "2 fold")
        self.assertEqual(stack(s, 3), 320)

    def test_41_two_all_ins_and_a_side_pot(self):
        s = spin(stacks={1: 450, 2: 150, 3: 300}, blinds="20/40")
        play(s, "1 raise 80, 2 allin, 3 allin")
        st = state(s)
        self.assertEqual(st.owe(1), 220)
        self.assertFalse(st.may_raise(1))
        play(s, "1 call")
        self.assertEqual([amount for amount, _ in pots(s)], [450, 300])
        s.do("award", ranking=[[2], [1]])
        self.assertEqual((stack(s, 2), stack(s, 1)), (450, 450))

    def test_a_lost_game_and_a_new_one(self):
        s = spin()
        play(s, "1 allin, 2 call, 3 fold")
        view = s.do("award", hero="lost")
        self.assertEqual(view["strip"]["tally"], {"games": 1, "wins": 0})
        self.assertEqual(view["strip"]["game"]["over"], "lost")
        view = s.do("new_game", start_stack=500)
        self.assertEqual([x["stack"] for x in view["table"]["seats"]], [500, 500, 500])
        self.assertIsNone(view["strip"]["game"]["over"])
        refused(s, "set_size", size=6)


# --------------------------------------------------------------------------
# Cases 42 to 45: All-In or Fold (amounts in big blinds, fee 0.1)
# --------------------------------------------------------------------------

def aof(stacks=None):
    s = Session(save=False)
    s.do("set_mode", mode="aof")
    s.do("new_session", button=1)                       # CO seat 4, BTN seat 1 (hero), SB 2, BB 3
    for seat, chips in (stacks or {}).items():
        s.do("set_stack", seat=seat, text=chips)
    s.do("deal")
    return s


class AllInOrFold(unittest.TestCase):
    def test_defaults(self):
        view = aof().view()
        self.assertEqual((view["mode"], view["unit"], view["table"]["size"]), ("aof", "bb", 4))
        self.assertEqual({x["seat"]: x["pos"] for x in view["table"]["seats"]}, {4: "CO", 1: "BTN", 2: "SB", 3: "BB"})
        level = view["strip"]["level"]
        self.assertEqual((level["sb"], level["bb"], level["ante"]), (0.5, 1, 0))
        self.assertEqual(view["strip"]["tally"]["net_bb"], 0)
        self.assertEqual(view["hand"]["legal"], {"fold": True, "check": False, "call": None, "bet": None,
                                                 "raise": None, "allin": 8})
        self.assertEqual(view["hand"]["presets"], [{"label": "All-in", "to": 8}])

    def test_42_only_all_in_or_fold(self):
        s = aof()
        self.assertEqual(state(s).pot_total(), 1.5)
        self.assertIn("all-in and fold", refused(s, "act", seat=4, kind="raise", amount=2.5).message)
        refused(s, "act", seat=4, kind="call")
        refused(s, "level_up")
        view = play(s, "4 fold, 1 fold, 2 fold")
        self.assertEqual(view["hand"]["phase"], "done")
        self.assertAlmostEqual(stack(s, 3), 8.4)        # a walk: the fee is taken all the same

    def test_43_the_cap(self):
        s = aof()
        view = play(s, "4 fold, 1 allin, 2 fold, 3 fold")
        self.assertAlmostEqual(stack(s, 1), 9.4)
        self.assertAlmostEqual(view["strip"]["tally"]["net_bb"], 1.4)
        view = s.do("deal")
        seat = [x for x in view["table"]["seats"] if x["seat"] == 1][0]
        self.assertEqual(seat["stack"] + seat["bet"], 8)            # cut to 8 big blinds at the deal
        self.assertAlmostEqual(view["strip"]["tally"]["banked"], 1.4)
        self.assertAlmostEqual(view["strip"]["tally"]["net_bb"], 1.4)

    def test_44_three_all_ins(self):
        s = aof({2: 5.5})
        play(s, "4 allin, 1 allin, 2 allin, 3 fold")
        self.assertEqual([amount for amount, _ in pots(s)], [17.5, 5])
        s.do("award", ranking=[[2], [1]])
        self.assertAlmostEqual(stack(s, 2), 17.4)
        self.assertAlmostEqual(stack(s, 1), 5.0)

    def test_45_a_call_is_an_all_in(self):
        s = aof({2: 5.5})
        view = play(s, "4 fold, 1 fold, 2 allin, 3 call")
        last = view["hand"]["line"][-1]
        self.assertEqual((last["verb"], last["to"]), ("call", 5.5))     # a call of 4.5 more
        self.assertEqual((view["hand"]["pot"], view["hand"]["phase"]), (11, "showdown"))
        s.do("award", ranking=[[2], [3]])
        self.assertAlmostEqual(stack(s, 2), 10.9)
        self.assertAlmostEqual(stack(s, 3), 2.5)

    def test_a_busted_seat_sits_down_again(self):
        s = aof()
        play(s, "4 fold, 1 allin, 2 allin, 3 fold")
        view = s.do("award", winner=2)
        self.assertAlmostEqual(view["strip"]["tally"]["net_bb"], -8)
        self.assertEqual(stack(s, 1), 8)                # a new stack of 8 big blinds
        self.assertEqual(view["hand"]["result"]["busted"], [1])


# --------------------------------------------------------------------------
# The table and the tournament
# --------------------------------------------------------------------------

class TableAndTournament(unittest.TestCase):
    def test_tournament_defaults(self):
        s = Session(save=False)
        view = s.view()
        self.assertTrue(view["first_run"])
        self.assertEqual((view["mode"], view["unit"], view["deck"], view["table"]["size"]),
                         ("tournament", "chips", "one-ink", 8))
        self.assertIsNone(view["hand"])
        self.assertEqual([x["stack"] for x in view["table"]["seats"]], [10000] * 8)
        self.assertEqual([x["stale"] for x in view["table"]["seats"]], [False] + [True] * 7)
        self.assertEqual(view["table"]["seats"][0]["name"], "You")
        self.assertTrue(view["table"]["seats"][0]["is_hero"])
        self.assertEqual({x["seat"]: x["pos"] for x in view["table"]["seats"]},
                         {1: "BTN", 2: "SB", 3: "BB", 4: "UTG", 5: "UTG+1", 6: "LJ", 7: "HJ", 8: "CO"})
        strip = view["strip"]
        self.assertEqual((strip["level"]["sb"], strip["level"]["bb"], strip["level"]["ante"],
                          strip["level"]["ante_kind"], strip["level"]["number"]), (50, 100, 12, "player", 1))
        self.assertEqual((strip["style"], strip["plan"], strip["opponents"]), ("survive", "full", "unknown"))
        self.assertEqual((strip["icm"], strip["stage"]["code"], strip["tally"]), ("off", "unknown", None))
        self.assertFalse(s.do("deal")["first_run"])

    def test_ladders(self):
        for name, ladder in D.LADDERS.items():
            blinds = [bb for _, bb, _ in ladder["levels"]]
            self.assertEqual(blinds, sorted(blinds), name)
            self.assertTrue(all(sb <= bb for sb, bb, _ in ladder["levels"]), name)
        self.assertEqual(D.SPIN_LEVELS[0][:2], (10, 20))
        self.assertEqual(D.SPIN_LEVELS[-1][:2], (1500, 3000))
        # past the end: 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, then times ten
        steps, bb = [], 3000
        for _ in range(8):
            bb = next_big_blind(bb)
            steps.append(bb)
        self.assertEqual(steps, [4000, 5000, 6000, 8000, 10000, 12500, 15000, 20000])

    def test_blinds_up_down_and_typed(self):
        s = Session(save=False)
        self.assertEqual(s.do("level_up")["strip"]["level"]["bb"], 150)
        self.assertEqual(s.do("level_down")["strip"]["level"]["bb"], 100)
        refused(s, "level_down")
        level = s.do("set_level", text="300/600/75")["strip"]["level"]
        self.assertEqual((level["sb"], level["bb"], level["ante"], level["number"]), (300, 600, 75, 7))
        self.assertEqual(s.do("level_up")["strip"]["level"]["bb"], 800)
        level = s.do("set_level", text="600")["strip"]["level"]     # the big blind alone
        self.assertEqual((level["sb"], level["ante"]), (300, 75))
        level = s.do("set_level", text="450/900")["strip"]["level"]  # not on the ladder
        self.assertEqual((level["sb"], level["bb"], level["ante"], level["number"]), (450, 900, 113, None))
        self.assertEqual(s.do("level_up")["strip"]["level"]["bb"], 1000)
        s.do("set_level", text="450/900")
        self.assertEqual(s.do("level_down")["strip"]["level"]["bb"], 800)
        level = s.do("set_ante_kind", kind="bb")["strip"]["level"]
        self.assertEqual((level["ante"], level["ante_kind"]), (800, "bb"))
        level = s.do("set_ante_kind")["strip"]["level"]             # cycles: none, player, bb, none
        self.assertEqual((level["ante"], level["ante_kind"]), (0, "none"))
        level = s.do("set_level", text="400/800/800")["strip"]["level"]
        self.assertEqual(level["ante_kind"], "bb")
        refused(s, "set_level", text="600/300")
        level = s.do("set_level", sb=600, bb="1.2k", ante=150)["strip"]["level"]     # the three numbers one by one
        self.assertEqual((level["sb"], level["bb"], level["ante"], level["ante_kind"]), (600, 1200, 150, "bb"))
        refused(s, "set_level", sb=600)
        s = Session(save=False)
        level = s.do("set_level", text="50k/100k")["strip"]["level"]     # the last level of the ladder
        self.assertEqual((level["number"], level["ante"]), (len(D.TURBO_LEVELS), 12500))
        level = s.do("level_up")["strip"]["level"]      # past the end the ladder goes on by the rule
        self.assertEqual((level["sb"], level["bb"], level["ante"], level["number"]),
                         (62500, 125000, 15625, len(D.TURBO_LEVELS) + 1))
        self.assertEqual(s.do("level_up")["strip"]["level"]["bb"], 150000)
        self.assertEqual(s.do("level_down")["strip"]["level"]["bb"], 125000)

    def test_a_ladder_pasted_in(self):
        s = Session(save=False)
        s.do("set_level", text="300/600/75")
        view = s.do("set_ladder", text="100/200/25\n200/400/50\n300/600/100\n500/1000/150")
        self.assertEqual(view["settings"]["ladder"], "custom")
        self.assertEqual(view["settings"]["levels"][2], [300, 600, 100])
        self.assertEqual((view["strip"]["level"]["bb"], view["strip"]["level"]["number"]), (600, 3))
        self.assertEqual(s.do("level_up")["strip"]["level"]["bb"], 1000)
        view = s.do("set_ladder", name="regular")
        self.assertEqual(view["strip"]["level"]["bb"], 1000)
        refused(s, "set_ladder", name="nope")

    def test_seats(self):
        s = Session(save=False)
        s.do("rename", seat=4, name="Hal")
        s.do("set_type", seat=4, type="lag")
        s.do("note", seat=4, text="3-bets the button a lot")
        s.do("set_status", seat=4)
        view = s.do("set_stack", seat=4, text="12.5k")
        seat = view["table"]["seats"][3]
        self.assertEqual((seat["name"], seat["type"], seat["note"], seat["status"], seat["stack"], seat["stale"]),
                         ("Hal", "lag", "3-bets the button a lot", "away", 12500, False))
        self.assertEqual(s.do("set_stack", seat=4, text="+3k")["table"]["seats"][3]["stack"], 15500)
        self.assertEqual(s.do("set_type", seat=4, type="s")["table"]["seats"][3]["type"], "station")
        refused(s, "set_type", seat=4, type="wizard")
        view = s.do("clear_seat", seat=4)
        self.assertTrue(view["table"]["seats"][3]["empty"])
        self.assertIn("left", view["toast"]["text"])
        refused(s, "set_stack", seat=4, text=500)
        refused(s, "clear_seat", seat=1)
        view = s.do("seat_player", seat=4, name="Gus", stack="20bb")
        self.assertEqual((view["table"]["seats"][3]["name"], view["table"]["seats"][3]["stack"]), ("Gus", 2000))
        view = s.do("set_size", size=9)
        self.assertEqual((view["table"]["size"], view["table"]["seats"][8]["empty"]), (9, True))
        refused(s, "set_size", size=7)                  # seat 8 is taken
        refused(s, "set_size", size=10)
        view = s.do("set_stacks", values=["9800", "", "-", "+500", "12k", "", "", "", "7000"])
        self.assertEqual([x["stack"] for x in view["table"]["seats"]],
                         [9800, 10000, 0, 2500, 12000, 10000, 10000, 10000, 7000])
        self.assertTrue(view["table"]["seats"][2]["empty"])
        self.assertFalse(view["table"]["seats"][8]["empty"])

    def test_between_hands_the_table_shows_the_next_deal(self):
        s = table_a()
        view = s.do("close_round")                      # everybody folds: the big blind wins
        self.assertEqual((view["hand"]["phase"], view["table"]["button"]), ("done", 2))
        self.assertEqual({x["seat"]: x["pos"] for x in view["table"]["seats"]}[HERO], "CO")
        self.assertEqual([i["pos"] for i in view["hand"]["line"]][:1], ["LJ"])      # the line keeps the hand's own names
        view = s.do("button_step", step=-1)             # a correction is seen at once
        self.assertEqual((view["table"]["button"], view["table"]["seats"][0]["pos"]), (1, "BTN"))
        self.assertEqual(s.do("deal")["table"]["button"], 1)

    def test_the_engine_orders_the_seats_the_same_way(self):
        rng = random.Random(3)
        for _ in range(60):
            size = rng.randint(2, 9)
            s = Session(save=False)
            s.do("new_session", size=size, button=rng.randint(1, size))
            for seat in range(2, size + 1):
                if rng.random() < 0.25 and len(s.data["table"]["seats"]) > 2:
                    s.do("clear_seat", seat=seat)
            s.do("deal")
            order = s.data["hand"]["order"]
            self.assertEqual(S.action_order(s.engine_state()), order)
            self.assertEqual(S.positions(s.engine_state()), state(s).labels)       # and names them the same

    def test_a_new_session_in_another_mode(self):
        s = Session(save=False)
        view = s.do("new_session", mode="spin")
        self.assertEqual((view["mode"], view["table"]["size"], view["first_run"]), ("spin", 3, False))
        self.assertEqual([x["stale"] for x in view["table"]["seats"]], [False] * 3)
        view = s.do("new_session", mode="tournament", size=6, start_stack="20k", level="300/600/75", button=5,
                    remaining=96, paid=75, entrants=500, style="cash")
        self.assertEqual((view["mode"], view["table"]["size"], view["table"]["button"]), ("tournament", 6, 5))
        self.assertEqual((view["strip"]["level"]["bb"], view["strip"]["remaining"], view["strip"]["style"]),
                         (600, 96, "cash"))
        self.assertEqual([x["stack"] for x in view["table"]["seats"]], [20000] * 6)
        for mode, low in (("spin", 3), ("aof", 4)):
            s.do("set_mode", mode=mode)
            self.assertIn(f"{low} seats", refused(s, "set_size", delta=1).message)
            refused(s, "new_session", size=low - 1)

    def test_players_left_marks_do_not_pile_up(self):
        s = Session(save=False)
        s.do("set_tournament", remaining=900)
        for _ in range(D.REMAINING_MARKS_KEPT + 40):
            s.do("remaining", delta=-1)
        self.assertEqual(len(s.data["tournament"]["history"]), D.REMAINING_MARKS_KEPT)
        self.assertEqual(s.data["tournament"]["history"][-1]["remaining"], 900 - D.REMAINING_MARKS_KEPT - 40)

    def test_button(self):
        s = Session(save=False)
        self.assertEqual(s.do("set_button", seat=4)["table"]["button"], 4)
        self.assertEqual(s.do("button_step", step=1)["table"]["button"], 5)
        self.assertEqual(s.do("button_step", step=-1)["table"]["button"], 4)
        s.do("clear_seat", seat=3)
        self.assertEqual(s.do("button_step", step=-1)["table"]["button"], 2)    # over the empty seat
        view = s.do("set_button", seat=3)               # a dead button: the last player before it acts as the button
        self.assertEqual({x["seat"]: x["pos"] for x in view["table"]["seats"] if not x["empty"]}[2], "BTN")
        refused(s, "set_button", seat=12)

    def test_a_table_move(self):
        s = Session(save=False)
        s.do("set_tournament", entrants=500, remaining=250, paid=75)
        s.do("rename", seat=3, name="Hal")
        s.do("set_stack", seat=1, text=14300)
        s.do("deal")
        view = s.do("new_table", size=6)
        self.assertIsNone(view["hand"])
        self.assertEqual(view["table"]["size"], 6)
        self.assertEqual([x["name"] for x in view["table"]["seats"]], ["You", "", "", "", "", ""])
        self.assertEqual(view["table"]["seats"][0]["stack"], 14300)
        self.assertEqual([x["stack"] for x in view["table"]["seats"][1:]], [20000] * 5)   # the average: 500 x 10,000 / 250
        self.assertTrue(all(x["stale"] for x in view["table"]["seats"][1:]))
        self.assertEqual(view["strip"]["remaining"], 250)

    def test_tournament_strip(self):
        s = Session(save=False)
        s.do("set_level", text="300/600/75")
        view = s.do("set_tournament", remaining=96, paid=75)
        self.assertEqual((view["strip"]["remaining"], view["strip"]["paid"]), (96, 75))
        self.assertEqual(view["strip"]["stage"], {"code": "approach", "label": "21 FROM THE MONEY"})
        self.assertEqual(view["strip"]["icm"], "estimated")
        view = s.do("set_tournament", entrants=500, buyin="11")
        self.assertEqual((view["strip"]["avg_stack"], view["strip"]["avg_bb"], view["strip"]["icm"]),
                         (52083, 86.8, "on"))
        view = s.do("set_tournament", field="payouts", text="1:1000 2:600 4-6:200")
        self.assertEqual((view["strip"]["icm"], view["strip"]["payouts"][:3]), ("exact", [1000, 600, 200]))
        self.assertEqual(s.do("set_tournament", payouts="auto")["strip"]["icm"], "on")
        view = s.do("set_tournament", avg_stack="40bb")     # read from the lobby: it wins
        self.assertEqual(view["strip"]["avg_stack"], 24000)
        self.assertEqual(s.do("remaining", delta=-1)["strip"]["remaining"], 95)
        self.assertEqual(s.do("remaining", value="140")["strip"]["stage"],
                         {"code": "approach", "label": "65 FROM THE MONEY"})
        self.assertEqual(s.do("remaining", value=78)["strip"]["stage"], {"code": "bubble", "label": "BUBBLE"})
        self.assertEqual(s.do("remaining", value=60)["strip"]["stage"]["code"], "itm")
        self.assertEqual(s.do("remaining", value=400)["strip"]["stage"], {"code": "early", "label": "EARLY"})
        self.assertEqual(len(s.data["tournament"]["history"]), 6)       # each change of players left is time-stamped
        view = s.do("set_config", reentry_open=True)
        self.assertEqual((view["strip"]["reentry_open"], view["strip"]["icm"]), (True, "off"))
        view = s.do("set_tournament", paid=900)
        self.assertIn("more than", view["toast"]["text"])
        refused(s, "remaining", value=0)

    def test_settings(self):
        s = Session(save=False)
        view = s.do("set_config", style="maxev", plan="all-in or fold", opponents="loose", bounty=True)
        self.assertEqual((view["strip"]["style"], view["strip"]["plan"], view["strip"]["opponents"],
                          view["strip"]["bounty"]), ("maxev", "allin", "loose", True))
        self.assertTrue(view["can"]["undo"])
        s = Session(save=False)
        view = s.do("set_config", unit="bb", deck="four-colour")
        self.assertEqual((view["unit"], view["deck"]), ("bb", "four-colour"))
        self.assertFalse(view["can"]["undo"])           # how numbers are drawn is not an undo step
        self.assertEqual(s.do("set_config", key="unit")["unit"], "chips")       # no value: the next option
        refused(s, "set_config", style="reckless")
        refused(s, "set_config", colour="red")

    def test_the_engine_gets_what_it_needs(self):
        s = Session(save=False)
        s.do("set_level", text="300/600/75")
        s.do("set_tournament", remaining=96, paid=75, entrants=500)
        s.do("set_type", seat=3, type="nit")
        s.do("set_config", opponents="loose")
        s.do("set_status", seat=4, status="away")
        st = s.engine_state()
        self.assertEqual(S.occupied(st), list(range(1, 9)))
        self.assertEqual(S.positions(st)[1], "BTN")
        self.assertEqual(S.blinds(st), (300.0, 600.0, 75.0, 0.0))
        self.assertEqual((st["table"]["seats"]["3"]["type"], st["table"]["seats"]["2"]["type"],
                          st["table"]["seats"]["1"]["type"], st["table"]["seats"]["4"]["status"]),
                         ("nit", "loose", "unknown", "away"))
        self.assertEqual(S.stage(st)["code"], "near_bubble")
        self.assertIn("ICM", S.build_prizes(st).label)
        self.assertEqual(st["config"]["goal"], "balanced")
        s.do("set_config", style="cash")
        self.assertEqual(s.engine_state()["config"]["goal"], "itm")
        setup, order = S.hand_setup(st)
        self.assertEqual((setup.n, order[-1]), (8, 3))
        self.assertIsNotNone(S.fold_clock(st))
        self.assertEqual(stage_of(s.data)["code"], "approach")
        self.assertEqual(icm_level(s.data), "on")
        self.assertEqual(session_level(s.data)["ante_kind"], "player")
        self.assertEqual(engine_state(s.data)["tournament"]["remaining"], 96)


# --------------------------------------------------------------------------
# Results, history, advice shown
# --------------------------------------------------------------------------

class Results(unittest.TestCase):
    def test_hero_won_lost_split(self):
        for said, hero, villain in (("won", 10500, 9500), ("lost", 9500, 10500), ("split", 10000, 10000)):
            s = new_table(size=2, blinds="50/100/0", button=1)
            play(s, "1 raise 500, 2 call, 2 check, 1 check, 2 check, 1 check, 2 check, 1 check")
            s.do("award", hero=said)
            self.assertEqual((stack(s, 1), stack(s, 2)), (hero, villain), said)

    def test_the_cards_decide_when_they_are_known(self):
        s = new_table(size=3, blinds="50/100/0", button=1)
        s.do("set_cards", hero="AhAd")
        play(s, "1 raise 300, 2 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        play(s, "2 check, 3 check, 1 check")
        s.do("set_cards", board="9h")
        play(s, "2 check, 3 check, 1 check")
        s.do("set_cards", board="3s")
        play(s, "2 check, 3 check, 1 check")
        self.assertEqual(refused(s, "award").message, "Who won?")
        s.do("set_cards", shown={2: "KhKd", 3: "QsQh"})
        view = s.do("award")
        self.assertEqual(view["hand"]["result"]["winners"], [{"seat": 2, "name": "", "pos": "SB", "amount": 900}])
        self.assertEqual(view["hand"]["result"]["text"], "SB wins 900")

    def test_history_and_what_the_coach_said(self):
        s = table_a()
        s.do("set_cards", hero="AhKd")
        s.do("act", seat=LJ, kind="raise", amount=500)
        self.assertTrue(s.record_advice(s.rev, "RAISE", {"kind": "raise", "to": 1500}))
        self.assertFalse(s.record_advice(s.rev - 1, "FOLD"))        # advice for an older table is dropped
        s.do("act", kind="raise", amount=1500)
        s.do("close_round", callers=[LJ])
        s.do("set_cards", board="Ks7d2c")
        s.do("act", seat=LJ, kind="check")
        s.do("act", kind="check", advice="BET")                     # the browser may send what it showed
        s.do("act", seat=LJ, kind="check")
        s.do("act", kind="bet", amount="50%")
        view = s.do("act", seat=LJ, kind="fold")
        entry = view["history"][0]
        self.assertEqual((entry["no"], entry["cards"], entry["pos"], entry["advice"], entry["did"],
                          entry["deviated"], entry["net"]), (1, "AhKd", "BTN", "BET", "check", True, 1800))
        self.assertIn("Coach (preflop): RAISE | you: raise", entry["text"])
        self.assertIn("Coach (flop): BET | you: check | deviated", entry["text"])
        self.assertIn("Flop Ks 7d 2c", entry["text"])
        self.assertIn("You win 3,300", entry["text"])
        deltas = {x["seat"]: x["delta"] for x in view["table"]["seats"]}
        self.assertEqual((deltas[1], deltas[LJ], deltas[SB]), (1800, -1500, -100))
        self.assertEqual(view["hand"]["needs"], "next")

    def test_needs(self):
        s = table_a()
        self.assertEqual(s.view()["hand"]["needs"], "cards")
        self.assertEqual(s.do("set_cards", hero="AKs")["hand"]["needs"], "action")
        play(s, "4 call, 1 call")
        view = s.do("close_round")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("flop", "cards"))   # the suits now
        self.assertEqual(s.do("set_cards", hero="AsKs")["hand"]["needs"], "board")
        self.assertEqual(s.do("set_cards", board="Qs7d2c")["hand"]["needs"], "action")
        play(s, "3 check, 4 allin, 1 call, 3 fold")
        view = s.view()
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"], view["hand"]["target"]),
                         ("showdown", "result", None))
        self.assertEqual(s.do("award", hero="won")["hand"]["needs"], "next")
        self.assertEqual(refused(s, "act", kind="fold").fix, "Undo to reopen it, or deal the next hand (N).")

    def test_hero_busts(self):
        s = table_a(remaining=50, paid=10)
        play(s, "4 allin, 1 call")
        s.do("close_round")
        view = s.do("award", hero="lost")
        seat = view["table"]["seats"][0]
        self.assertEqual((seat["empty"], seat["stack"], seat["status"]), (False, 0, "busted"))
        self.assertEqual(view["strip"]["remaining"], 49)
        self.assertIn("You are out", view["toast"]["text"])
        view = s.do("deal")                             # the table plays on without him
        self.assertFalse(view["table"]["seats"][0]["in_hand"])
        s.do("discard_hand")
        view = s.do("set_stack", seat=1, text=10000)    # a re-entry
        self.assertEqual(view["table"]["seats"][0]["status"], "active")


# --------------------------------------------------------------------------
# Undo, redo, saving
# --------------------------------------------------------------------------

class UndoAndSaving(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="poker app test ")    # a path with spaces, as on Windows
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_undo_walks_back_across_hands(self):
        s = table_a()
        setup_steps = len(s.data["journal"]["undo"])
        snapshots = [json.dumps(s.view(), sort_keys=True)]
        steps = [("act", dict(seat=4, kind="raise", amount=500)), ("close_round", {}), ("deal", {}),
                 ("set_stack", dict(seat=3, text="5k")), ("level_up", {}), ("bust", dict(seat=5)),
                 ("act", dict(seat=1, kind="allin")), ("close_round", {}), ("deal", {}), ("rename", dict(seat=2, name="Bo"))]
        for op, args in steps:
            s.do(op, **args)
            snapshots.append(json.dumps(s.view(), sort_keys=True))

        def same(view, text):                           # the revision and the undo flags move on; nothing else differs
            view, old = dict(view, rev=0, can=0, toast=0), dict(json.loads(text), rev=0, can=0, toast=0)
            return json.dumps(view, sort_keys=True) == json.dumps(old, sort_keys=True)

        for k in range(len(steps) - 1, -1, -1):
            self.assertTrue(same(s.do("undo"), snapshots[k]), steps[k])
        self.assertEqual(len(s.data["journal"]["undo"]), setup_steps)
        self.assertFalse(Session(save=False).view()["can"]["undo"])
        refused(Session(save=False), "undo")
        for k in range(1, len(steps) + 1):
            self.assertTrue(same(s.do("redo"), snapshots[k]), steps[k - 1])
        refused(s, "redo")
        s.do("undo")
        s.do("rename", seat=2, name="Al")               # a new change clears what could be redone
        self.assertFalse(s.view()["can"]["redo"])

    def test_undo_is_capped(self):
        s = Session(save=False)
        for k in range(D.UNDO_LIMIT + 30):
            s.do("rename", seat=2, name=f"n{k}")
        self.assertEqual(len(s.data["journal"]["undo"]), D.UNDO_LIMIT)

    def test_a_new_session_can_be_undone(self):
        s = table_a()
        s.do("close_round")
        self.assertEqual(len(s.view()["history"]), 1)
        view = s.do("new_session", size=4)
        self.assertEqual((view["table"]["size"], view["history"]), (4, []))
        view = s.do("undo")
        self.assertEqual((view["table"]["size"], len(view["history"])), (6, 1))
        self.assertEqual(s.do("redo")["history"], [])
        self.assertEqual(len(s.do("undo")["history"]), 1)

    def test_every_change_is_saved_and_loaded(self):
        s = Session(self.folder)
        s.do("set_level", text="300/600/75")
        s.do("rename", seat=4, name="Hal")
        s.do("deal", hero_cards="AhKd")
        s.do("act", seat=4, kind="raise", amount="2.2bb")
        before = s.view()
        self.assertEqual(sorted(os.listdir(self.folder)), ["app.json", "tournament.json"])
        again = Session(self.folder)
        self.assertEqual(again.view(), before)
        self.assertEqual(again.do("undo")["hand"]["line"][-1]["kind"], "cards")     # the undo history is saved too
        self.assertFalse([name for name in os.listdir(self.folder) if name.endswith(".tmp")])

    def test_each_mode_has_its_own_file(self):
        s = Session(self.folder)
        s.do("rename", seat=2, name="Tourney")
        view = s.do("set_mode", mode="spin")
        self.assertEqual((view["mode"], view["table"]["size"], view["first_run"]), ("spin", 3, True))
        s.do("rename", seat=2, name="Spinner")
        s.do("set_mode", mode="aof")
        s.do("deal")
        self.assertEqual(sorted(os.listdir(self.folder)), ["aof.json", "app.json", "spin.json", "tournament.json"])
        again = Session(self.folder)
        self.assertEqual(again.view()["mode"], "aof")               # the mode on screen is remembered
        self.assertEqual(again.view()["hand"]["no"], 1)
        self.assertEqual(again.do("set_mode", mode="tournament")["table"]["seats"][1]["name"], "Tourney")
        self.assertEqual(again.do("set_mode", mode="spin")["table"]["seats"][1]["name"], "Spinner")
        self.assertFalse(again.view()["can"]["undo"] and again.view()["mode"] != "spin")
        refused(again, "set_mode", mode="cash")

    def test_modes_keep_their_sessions_in_memory_too(self):
        s = Session(save=False)
        s.do("rename", seat=2, name="Tourney")
        s.do("set_mode", mode="spin")
        s.do("rename", seat=2, name="Spinner")
        view = s.do("undo")                             # each mode has its own undo history
        self.assertEqual((view["table"]["seats"][1]["name"], view["can"]), ("", {"undo": False, "redo": True}))
        view = s.do("set_mode", mode="tournament")
        self.assertEqual((view["table"]["seats"][1]["name"], view["can"]["undo"]), ("Tourney", True))
        self.assertEqual(s.do("set_mode", mode="spin")["can"], {"undo": False, "redo": True})

    def test_the_revision_goes_up_with_every_accepted_intent(self):
        s = Session(self.folder)
        rev = s.rev
        s.do("deal")
        s.do("set_config", unit="bb")
        s.do("undo")
        self.assertEqual(s.rev, rev + 3)
        refused(s, "act", seat=1, kind="fold")
        self.assertEqual(s.rev, rev + 3)
        self.assertEqual(Session(self.folder).rev, rev + 3)

    def test_a_broken_file_is_set_aside(self):
        s = Session(self.folder)
        s.do("deal")
        with open(os.path.join(self.folder, "tournament.json"), "w") as fh:
            fh.write("{not json")
        again = Session(self.folder)
        self.assertIsNone(again.view()["hand"])
        self.assertIn("tournament.json.unreadable", os.listdir(self.folder))


# --------------------------------------------------------------------------
# The view: every key of the build spec, with the right type
# --------------------------------------------------------------------------

NUMBER = (int, float)
OPTIONAL_NUMBER = (int, float, type(None))

VIEW = {"rev": int, "mode": str, "unit": str, "deck": str, "can": dict, "strip": dict, "table": dict,
        "hand": (dict, type(None)), "history": list, "toast": (dict, type(None))}
STRIP = {"level": dict, "remaining": (int, type(None)), "paid": (int, type(None)), "entrants": (int, type(None)),
         "start_stack": OPTIONAL_NUMBER, "buyin": OPTIONAL_NUMBER, "avg_stack": OPTIONAL_NUMBER,
         "avg_bb": OPTIONAL_NUMBER, "stage": dict, "icm": str, "style": str, "plan": str, "opponents": str,
         "reentry_open": bool, "bounty": bool, "tally": (dict, type(None))}
LEVEL = {"number": (int, type(None)), "sb": NUMBER, "bb": NUMBER, "ante": NUMBER, "ante_kind": str,
         "pending": (dict, type(None))}
SEAT = {"seat": int, "empty": bool, "is_hero": bool, "name": str, "pos": str, "is_button": bool,
        "stack": NUMBER, "stack_bb": NUMBER, "stale": bool, "status": str, "type": str, "note": str,
        "in_hand": bool, "folded": bool, "all_in": bool, "bet": NUMBER, "bet_bb": NUMBER, "is_target": bool,
        "delta": OPTIONAL_NUMBER}
HAND = {"no": int, "phase": str, "needs": str, "hero_cards": list, "hero_class": str, "board": list,
        "pot": NUMBER, "pot_bb": NUMBER, "to_call": NUMBER, "to_call_bb": NUMBER,
        "target": (int, type(None)), "target_is_hero": bool, "legal": (dict, type(None)), "presets": list,
        "line": list, "pots": list, "result": (dict, type(None))}
LEGAL = {"fold": bool, "check": bool, "call": OPTIONAL_NUMBER, "bet": (dict, type(None)),
         "raise": (dict, type(None)), "allin": OPTIONAL_NUMBER}
ACT_ITEM = {"i": int, "kind": str, "seat": int, "pos": str, "name": str, "verb": str, "to": NUMBER,
            "text": str, "auto": bool}
HISTORY = {"no": int, "cards": str, "pos": str, "advice": str, "did": str, "deviated": bool,
           "net": OPTIONAL_NUMBER, "text": str}


class TheView(unittest.TestCase):
    def shaped(self, thing, shape, where):
        for key, kind in shape.items():
            self.assertIn(key, thing, f"{where}: {key} is missing")
            self.assertIsInstance(thing[key], kind, f"{where}.{key}")
            if kind in (int, NUMBER, OPTIONAL_NUMBER):
                self.assertNotIsInstance(thing[key], bool, f"{where}.{key}")

    def check(self, view):
        json.dumps(view)
        self.shaped(view, VIEW, "view")
        self.assertEqual(set(view["can"]), {"undo", "redo"})
        self.assertIn(view["mode"], D.MODES)
        self.assertIn(view["unit"], D.UNITS)
        self.assertIn(view["deck"], D.DECKS)
        strip = view["strip"]
        self.shaped(strip, STRIP, "strip")
        self.shaped(strip["level"], LEVEL, "strip.level")
        self.assertIn(strip["level"]["ante_kind"], D.ANTE_KINDS)
        self.assertEqual(set(strip["stage"]), {"code", "label"})
        self.assertIn(strip["stage"]["code"], ("unknown", "early", "middle", "approach", "bubble", "itm", "final"))
        self.assertIn(strip["icm"], ("off", "estimated", "on", "exact"))
        self.assertIn(strip["style"], D.STYLES)
        self.assertIn(strip["plan"], D.PLANS)
        if view["mode"] == "spin":
            self.assertEqual(set(strip["tally"]) & {"games", "wins"}, {"games", "wins"})
        elif view["mode"] == "aof":
            self.assertIn("net_bb", strip["tally"])
        else:
            self.assertIsNone(strip["tally"])
        table = view["table"]
        self.assertEqual([x["seat"] for x in table["seats"]], list(range(1, table["size"] + 1)))
        self.assertIsInstance(table["button"], int)
        for seat in table["seats"]:
            self.shaped(seat, SEAT, f"seat {seat['seat']}")
        self.assertEqual([x["seat"] for x in table["seats"] if x["is_hero"]], [1])
        hand = view["hand"]
        if hand:
            self.shaped(hand, HAND, "hand")
            self.assertIn(hand["phase"], ("preflop", "flop", "turn", "river", "showdown", "done"))
            self.assertIn(hand["needs"], ("cards", "action", "board", "result", "next"))
            self.assertEqual(hand["target_is_hero"], hand["target"] == 1)
            self.assertEqual([x["seat"] for x in table["seats"] if x["is_target"]],
                             [hand["target"]] if hand["target"] else [])
            if hand["legal"]:
                self.shaped(hand["legal"], LEGAL, "hand.legal")
                for box in (hand["legal"]["bet"], hand["legal"]["raise"]):
                    if box:
                        self.assertEqual(set(box), {"min", "max", "default"})
                        self.assertTrue(box["min"] <= box["default"] <= box["max"], box)
            for preset in hand["presets"]:
                self.assertEqual((set(preset), type(preset["label"])), ({"label", "to"}, str))
            for i, item in enumerate(hand["line"]):
                self.assertEqual(item["i"], i)
                self.assertIn(item["kind"], ("cards", "board", "act"))
                self.assertIsInstance(item["text"], str)
                if item["kind"] == "act":
                    self.shaped(item, ACT_ITEM, "line item")
                    self.assertIn(item["verb"], ("fold", "check", "call", "bet", "raise", "allin"))
            for pot in hand["pots"]:
                self.assertEqual(set(pot), {"amount", "eligible"})
        for entry in view["history"]:
            self.shaped(entry, HISTORY, "history entry")
        if view["toast"]:
            self.assertIsInstance(view["toast"]["text"], str)

    def test_shape_in_every_mode_and_phase(self):
        for mode in D.MODES:
            s = Session(save=False)
            self.check(s.do("set_mode", mode=mode))
            self.check(s.do("deal"))
            self.check(s.do("set_cards", hero="AhKd"))
            self.check(s.do("act", kind="allin"))
            self.check(s.do("act", seat=2, kind="call"))
            view = s.do("close_round") if s.view()["hand"]["phase"] in BETTING else s.view()
            self.check(view)
            self.assertEqual(view["hand"]["phase"], "showdown", mode)
            self.check(s.do("award", hero="won"))
            self.check(s.do("deal"))
            self.check(s.do("skip_hand"))
            self.check(s.do("undo"))
            self.check(s.view())

    def test_the_example_of_the_spec(self):
        s = Session(save=False)
        s.do("new_session", size=8, button=2)
        s.do("set_level", text="300/600/75")
        s.do("set_tournament", remaining=96, paid=75, entrants=500, buyin=11)
        s.do("set_stack", seat=1, text=12900)
        s.do("rename", seat=7, name="Hal")
        s.do("deal", hero_cards="AhKd")
        view = s.do("act", seat=7, kind="raise", amount="2.2bb")
        self.check(view)
        hero = view["table"]["seats"][0]
        self.assertEqual((hero["pos"], hero["stack"], hero["stack_bb"], hero["is_target"]),
                         ("CO", 12825, 21.4, True))
        hand = view["hand"]
        self.assertEqual((hand["hero_cards"], hand["hero_class"], hand["phase"], hand["needs"]),
                         (["Ah", "Kd"], "AKo", "preflop", "action"))
        self.assertEqual((hand["pot"], hand["pot_bb"], hand["to_call"], hand["to_call_bb"]),
                         (300 + 600 + 8 * 75 + 1320, 4.7, 1320, 2.2))
        self.assertEqual(hand["legal"], {"fold": True, "check": False, "call": 1320, "bet": None,
                                         "raise": {"min": 2040, "max": 12825, "default": 3960}, "allin": 12825})
        self.assertEqual(hand["presets"][-1], {"label": "All-in", "to": 12825})
        self.assertEqual(hand["line"][0], {"i": 0, "kind": "cards", "street": "preflop", "text": "AhKd"})
        last = hand["line"][-1]
        self.assertEqual((last["seat"], last["pos"], last["name"], last["verb"], last["to"], last["text"],
                          last["auto"]), (7, "LJ", "Hal", "raise", 1320, "Hal raise 2.2bb", False))
        self.assertEqual(hand["pots"], [{"amount": hand["pot"], "eligible": [7, 8, 1, 2, 3, 4]}])     # 5 and 6 folded
        self.assertEqual(view["strip"]["stage"]["label"], "21 FROM THE MONEY")


# --------------------------------------------------------------------------
# What the page needs beyond the build spec: who acts before the target, the key map, a word for
# the refusal the page reacts to, and the folder of a trial run
# --------------------------------------------------------------------------

class ForThePage(unittest.TestCase):
    def test_who_acts_before_the_target(self):
        s = Session(save=False)
        s.do("new_session", size=8, button=2)                       # hero is the cutoff
        view = s.do("deal", hero_cards="AKs")
        self.assertEqual((view["hand"]["target"], view["hand"]["before_target"]), (1, [5, 6, 7, 8]))
        view = s.do("act", seat=7, kind="raise")                    # typed: he is no longer "still to act"
        self.assertEqual(view["hand"]["before_target"], [8])
        view = s.do("act", kind="call")                             # hero has acted: the action is on the button
        self.assertEqual((view["hand"]["target"], view["hand"]["before_target"]), (2, []))
        view = s.do("close_round")                                  # the flop: the blinds folded, the raiser acts first
        self.assertEqual((view["hand"]["phase"], view["hand"]["target"], view["hand"]["before_target"]), ("flop", 1, [7]))
        view = s.do("skip_hand")
        self.assertIsNone(view["hand"])

    def test_the_side_pot_refusal_has_a_code(self):
        s = table_a(stacks={BB: 3000})
        play(s, "4 raise 500, 1 call, 3 allin, 4 call, 1 call")     # the big blind is all-in for less
        play(s, "4 bet 1000, 1 call")                               # the other two bet on: a side pot
        s.do("set_cards", hero="AhKd")
        s.do("set_cards", board="Ks7d2c9h3c")
        s.do("close_round")                                         # the river is checked through
        self.assertEqual(s.view()["hand"]["needs"], "result")
        err = refused(s, "award", ranking=[[BB]])
        self.assertEqual(err.code, "side_pot")
        self.assertIn("side pot", err.message)
        self.assertEqual(refused(s, "award", ranking=[[2]]).code, "")       # seat 2 folded: another refusal, no code
        s.do("award", ranking=[[BB], [1]])
        self.assertEqual(s.view()["hand"]["needs"], "next")

    def test_a_number_too_big_is_refused_like_any_other(self):
        s = Session(save=False)
        s.do("new_session", size=6)
        for intent in ({"op": "set_stack", "seat": 2, "text": "1e999"}, {"op": "set_stack", "seat": 2, "text": float("inf")},
                       {"op": "remaining", "value": "9" * 400}):
            err = refused(s, intent.pop("op"), **intent)
            self.assertTrue(err.message)

    def test_the_key_map(self):
        keys = Session(save=False).view()["settings"]["keys"]
        self.assertEqual(set(keys), {"table", "seat", "type"})
        for group, rows in keys.items():
            bound = [key for row in rows for key in row["keys"]]
            self.assertEqual(len(bound), len(set(bound)), f"a key is bound twice in {group}")
            for row in rows:
                self.assertEqual(set(row), {"keys", "do", "text"})
                self.assertTrue(row["keys"] and row["do"] and row["text"], row)
            # the seat digits and Tab are not for the map: digits name seats, Tab is the browser's
            self.assertFalse(set(bound) & set("123456789") | set(bound) & {"Tab", "Shift+Tab"}, group)
        table = {key: row["do"] for row in keys["table"] for key in row["keys"]}
        self.assertEqual((table["n"], table["Space"], table["Enter"], table["Backspace"], table["?"]),
                         ("deal", "follow", "accept", "undo", "keys"))
        self.assertEqual({row["do"] for row in keys["type"]}, set(PLAYER_TYPES))      # every player type has its key
        json.dumps(keys)

    def test_a_folder_of_its_own(self):
        from unittest import mock
        from poker_coach.app import model
        with tempfile.TemporaryDirectory(prefix="menlo trial ") as folder:
            with mock.patch.dict(os.environ, {"POKER_COACH_APP": folder}):
                self.assertEqual(model.default_folder(), folder)
                s = Session()
                s.do("new_session", size=6)
                self.assertEqual(sorted(os.listdir(folder)), ["app.json", "tournament.json"])
        with mock.patch.dict(os.environ):
            os.environ.pop("POKER_COACH_APP", None)
            self.assertTrue(model.default_folder().endswith(os.path.join("tournament", "app")))


if __name__ == "__main__":
    unittest.main()
