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


def saved_files(folder) -> list:
    """The session files in a folder (beside them: the .bak copies and the lock of a running program)."""
    return sorted(name for name in os.listdir(folder) if name.endswith(".json"))


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
        self.assertFalse(view["history"][0]["skipped"])                                 # hero folded: his hand is complete
        self.assertIn("Result: you folded", view["history"][0]["text"])
        self.assertEqual((view["history"][0]["net"], view["history"][0]["did"]), (0, "fold"))

    def test_a_stack_corrected_during_the_hand(self):
        s = table_a()
        play(s, "4 raise 500, 5 fold, 6 fold")
        s.do("set_stack", seat=LJ, text="7500")         # the chips he has behind now
        st = state(s)
        self.assertEqual((st.start[LJ], st.stack[LJ], st.in_front[LJ]), (8000, 7500, 500))
        s.do("discard_hand")
        self.assertEqual(stack(s, LJ), 8000)

    def test_button_corrected_during_the_hand(self):
        """ROB-2: before the first action the hand is posted again from the new button; after it the move is refused."""
        s = table_a()
        s.do("set_cards", hero="AKs")
        view = s.do("button_step", step=-1)             # the button is really on seat 6
        self.assertEqual(view["table"]["button"], 6)
        self.assertIn("posted again", view["toast"]["text"])
        st = state(s)
        self.assertEqual((st.labels[HERO], st.labels[4], st.blind[1], st.blind[2]), ("SB", "HJ", 100, 200))
        self.assertEqual(view["hand"]["hero_class"], "AKs")
        play(s, "4 raise 500")
        before = line_of(s)
        for op, args in (("button_step", {"step": 1}), ("button_step", {"step": -1}), ("set_button", {"seat": 2})):
            err = refused(s, op, **args)
            self.assertIn("Undo to before the first action", err.fix)
            self.assertIn("Ctrl+Backspace", err.fix)
        self.assertEqual((line_of(s), s.view()["table"]["button"]), (before, 6))

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
        self.assertEqual((view["strip"]["icm"], view["strip"]["payouts"][:3]), ("on", [1000, 600, 200]))   # 6 of 75 places
        view = s.do("set_tournament", field="payouts", text="1:1000 2:600 4-75:200")
        self.assertEqual((view["strip"]["icm"], len(view["strip"]["payouts"])), ("exact", 75))
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
        s.do("new_session")
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
        self.assertEqual(view["hand"]["result"]["text"], "Seat 2 (SB) wins 900")       # T4: by seat and position

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
        self.assertIn("Result: You (BTN) win 3,300", entry["text"])
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
        self.assertEqual(saved_files(self.folder), ["app.json", "tournament.json"])
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
        self.assertEqual(saved_files(self.folder), ["aof.json", "app.json", "spin.json", "tournament.json"])
        again = Session(self.folder)
        self.assertEqual(again.view()["mode"], "aof")               # the mode on screen is remembered
        self.assertEqual(again.view()["hand"]["no"], 1)
        self.assertEqual(again.do("set_mode", mode="tournament")["table"]["seats"][1]["name"], "Tourney")
        self.assertEqual(again.do("set_mode", mode="spin")["table"]["seats"][1]["name"], "Spinner")
        self.assertFalse(again.view()["can"]["undo"] and again.view()["mode"] != "spin")
        refused(again, "set_mode", mode="cash")

    def test_modes_keep_their_sessions_in_memory_too(self):
        s = Session(save=False)
        s.do("new_session")
        s.do("rename", seat=2, name="Tourney")
        s.do("set_mode", mode="spin")
        s.do("rename", seat=2, name="Spinner")           # the first change: the table undo stops at
        s.do("rename", seat=2, name="Spinner 2")
        view = s.do("undo")                             # each mode has its own undo history
        self.assertEqual((view["table"]["seats"][1]["name"], view["can"]), ("Spinner", {"undo": False, "redo": True}))
        view = s.do("set_mode", mode="tournament")
        self.assertEqual((view["table"]["seats"][1]["name"], view["can"]["undo"]), ("Tourney", True))
        self.assertEqual(s.do("set_mode", mode="spin")["can"], {"undo": False, "redo": True})

    def test_the_revision_goes_up_with_every_accepted_intent(self):
        s = Session(self.folder)
        s.do("new_session")
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
        self.assertEqual(len([n for n in os.listdir(self.folder) if n.startswith("tournament.json.unreadable-")]), 1)


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
                self.assertEqual(saved_files(folder), ["app.json", "tournament.json"])
        with mock.patch.dict(os.environ):
            os.environ.pop("POKER_COACH_APP", None)
            self.assertTrue(model.default_folder().endswith(os.path.join("tournament", "app")))


# ==========================================================================
# The review round.  One class per finding of the reports (OPS, POST, ROB, VIS and the package
# report), named after it; the reports are in docs/table-app/ once they are filed.
# ==========================================================================

def tournament(size=6, level="100/200/0", stacks=None, button=1, **fields):
    """A tournament set up in one intent, as the page's set-up form does it; no hand dealt."""
    s = Session(save=False)
    s.do("new_session", mode="tournament", size=size, start_stack=10000, level=level, button=button, **fields)
    if stacks:
        s.do("set_stacks", values=stacks)
    return s


def toast_of(view) -> str:
    return view["toast"]["text"] if view["toast"] else ""


def line_of(s) -> list:
    """The hand line as text; an action nobody typed carries a star."""
    return [item["text"] + ("*" if item.get("auto") else "") for item in s.view()["hand"]["line"]]


class Rob5NotANumber(unittest.TestCase):
    """ROB-5: nan, inf and 1e999 are not amounts, typed or sent as numbers; nothing of them is saved."""

    def test_rob_5_the_parser_refuses_what_is_not_finite(self):
        for typed in ("nan", "inf", "-inf", "infinity", "1e999", "1e3", float("nan"), float("inf"), 10 ** 400):
            for step in (1, 0.1, 0.01):
                with self.assertRaises(AmountError, msg=(typed, step)):
                    parse_amount(typed, bb=1, current=5, step=step)

    def test_rob_5_no_field_takes_it(self):
        s = aof()
        for op, args in (("set_stack", {"seat": 1, "text": "nan"}), ("set_stacks", {"values": ["nan", "inf"]}),
                         ("seat_player", {"seat": 2, "stack": "nan"}),
                         ("set_config", {"tally": {"hands": float("inf")}}),
                         ("set_config", {"tally": {"net_bb": float("nan")}}),
                         ("set_config", {"tally": {"net_bb": "1e999"}})):
            self.assertTrue(refused(s, op, **args).message, (op, args))
        t = tournament()
        for op, args in (("set_tournament", {"buyin": "inf"}), ("set_tournament", {"buyin": "nan"}),
                         ("set_tournament", {"payouts": "nan"}), ("set_tournament", {"payouts": "1:" + "9" * 60}),
                         ("set_tournament", {"avg_stack": float("inf")}),
                         ("new_session", {"start_stack": "nan"}), ("new_session", {"hero_stack": "inf"})):
            self.assertTrue(refused(t, op, **args).message, (op, args))
        json.dumps(t.view(), allow_nan=False)
        json.dumps(s.view(), allow_nan=False)

    def test_rob_5_the_tally_still_takes_a_loss(self):
        s = aof()
        s.do("set_config", tally={"net_bb": -12.5, "hands": 40})
        self.assertEqual(s.view()["strip"]["tally"]["net_bb"], -12.5)


class Rob6DotThousands(unittest.TestCase):
    """ROB-6: 12.500 is twelve thousand five hundred where chips are whole; 12.5 is never rounded to 13."""

    def test_rob_6_a_dot_before_three_digits_is_thousands(self):
        for typed, value in (("12.500", 12500), ("23.450", 23450), ("7.250", 7250), ("100.000", 100000),
                             ("1.300.000", 1300000), ("12,500", 12500), ("+3.000", 13000), ("12.5k", 12500),
                             ("12,5k", 12500), ("2.2bb", 1320), ("1300", 1300)):
            self.assertEqual(parse_amount(typed, bb=600, current=10000), value, typed)

    def test_rob_6_a_bare_fraction_is_refused_with_the_spellings_that_work(self):
        for typed in ("12.5", "12,5", "0.5", "12.50", "0.500", "1234.567"):
            with self.assertRaises(AmountError, msg=typed) as caught:
                parse_amount(typed, bb=600)
            self.assertIn("k", caught.exception.fix, typed)
        with self.assertRaises(AmountError) as caught:
            parse_amount("12.5", bb=600)
        self.assertEqual(caught.exception.fix, "Type 12500, or 12.5k, or 12.5bb.")
        with self.assertRaises(AmountError) as caught:
            parse_amount("12,5")                                    # no blinds known here: no bb spelling offered
        self.assertEqual(caught.exception.fix, "Type 12500, or 12,5k.")

    def test_rob_6_big_blind_tables_keep_the_decimal(self):
        self.assertEqual(parse_amount("7.5", bb=1, step=0.1), 7.5)
        self.assertEqual(parse_amount("7.500", bb=1, step=0.1), 7.5)
        s = aof()
        s.do("set_stack", seat=1, text="5.5")
        self.assertEqual(stack(s, 1), 5.5)

    def test_rob_6_stacks_blinds_average_entrants_and_the_set_up_form(self):
        s = tournament(size=6)
        s.do("set_stacks", values=["12.500", "23.450", "8.900", "31.000", "5.250", "17.800"])
        self.assertEqual([stack(s, n) for n in range(1, 7)], [12500, 23450, 8900, 31000, 5250, 17800])
        view = s.do("set_level", text="1.000/2.000/250")
        self.assertEqual([view["strip"]["level"][k] for k in ("sb", "bb", "ante")], [1000, 2000, 250])
        self.assertEqual(s.do("set_tournament", avg_stack="45.300")["strip"]["avg_stack"], 45300)
        self.assertEqual(s.do("set_tournament", entrants="1.500")["strip"]["entrants"], 1500)
        self.assertIn("fraction", refused(s, "set_stack", seat=2, text="12.5").message)
        form = Session(save=False)
        form.do("new_session", mode="tournament", size=6, start_stack="20.000", hero_stack="12.900", entrants="1.500")
        self.assertEqual((stack(form, 1), stack(form, 2), form.view()["strip"]["entrants"]), (12900, 20000, 1500))


class Rob9Limits(unittest.TestCase):
    """ROB-9: one ceiling for amounts, one for counts, and a prize list that cannot fill the memory."""

    def test_rob_9_amounts_and_counts_have_a_ceiling(self):
        s = tournament()
        self.assertEqual(s.do("set_stack", seat=2, text="1000000000000")["table"]["seats"][1]["stack"], 10 ** 12)
        for op, args in (("set_stack", {"seat": 2, "text": "1000000000001"}), ("set_stack", {"seat": 2, "text": 1e308}),
                         ("set_tournament", {"entrants": "9" * 24}), ("set_tournament", {"entrants": "10000001"}),
                         ("set_tournament", {"paid": 1e9}), ("remaining", {"value": "20000000"}),
                         ("set_tournament", {"payouts": "1-100000000:200"}),
                         ("set_tournament", {"payouts": "1:1000 2:600 3-30000000:20"})):
            err = refused(s, op, **args)
            self.assertTrue(err.message and err.fix, (op, args))
        self.assertEqual(s.do("set_tournament", entrants="10000000")["strip"]["entrants"], 10 ** 7)
        self.assertEqual(len(parse_payouts("1:1000 2-100000:5")), 100000)


class Ops18Blinds(unittest.TestCase):
    """OPS-18 and VIS-17 (17): each field refuses in its own words; an ante of one big blind is questioned."""

    def test_ops_18_unreadable_blinds_get_the_blinds_sentence(self):
        s = tournament()
        for typed in ("300-600-75", "abc", "x/y", "300/600/75/10"):
            err = refused(s, "set_level", text=typed)
            self.assertIn("as blinds", err.message, typed)
            self.assertIn("Type blinds like 300/600/75", err.fix, typed)
            self.assertNotIn("66%", err.fix)
        self.assertIn("300/600/75", refused(s, "set_level", sb="x", bb="600").fix)

    def test_ops_18_an_ante_as_big_as_the_big_blind_is_taken_and_questioned(self):
        s = tournament(level="300/600/75")                          # every player antes, as GGPoker has it
        view = s.do("set_level", text="250/500/500")
        level = view["strip"]["level"]
        self.assertEqual((level["ante"], level["ante_kind"]), (500, "player"))      # accepted as typed
        self.assertEqual(toast_of(view), "Ante 500 from every player. A big-blind ante? Shift+A switches it")
        self.assertEqual(s.do("set_ante_kind")["strip"]["level"]["ante_kind"], "bb")
        self.assertNotIn("Shift+A", toast_of(s.do("set_level", text="300/600/75")))

    def test_vis_17_each_field_has_its_own_sentence(self):
        s = tournament()
        self.assertEqual(refused(s, "set_tournament", field="paid", text="x").fix,
                         "Places paid is a whole number, like 75.")
        self.assertEqual(refused(s, "set_tournament", field="remaining", text="many").fix,
                         "Players left is a whole number, like 96.")
        self.assertEqual(refused(s, "remaining", value="12.5").fix, "Players left is a whole number, like 96.")
        self.assertIn("Entrants is a whole number", refused(s, "set_tournament", entrants="abc").fix)
        self.assertIn("average stack", refused(s, "set_tournament", avg_stack="abc").fix)
        self.assertIn("buy-in", refused(s, "set_tournament", buyin="abc").fix)
        for bad in ("x", "bb", "%", "k"):                           # a unit and no number is not "a multiple of a bet"
            self.assertIn("Cannot read", refused(s, "set_stack", seat=2, text=bad).message, bad)

    def test_vis_19_an_ante_nobody_typed_is_announced(self):
        s = tournament(level="300/600/75")
        text = toast_of(s.do("set_level", text="200/400"))
        self.assertIn("Ante 50 from the turbo levels", text)
        self.assertIn("200/400/0", text)
        self.assertIn("an eighth of the big blind", toast_of(s.do("set_level", text="210/420")))
        self.assertNotIn("Ante 50", toast_of(s.do("set_level", text="200/400/50")))     # typed: nothing to announce
        self.assertEqual(toast_of(s.do("set_level", text="200/400/0")), "No ante")
        self.assertEqual(toast_of(s.do("set_level", text="300/600")), "")               # no ante is played: no news
        s.do("set_ante_kind", kind="player")
        self.assertIn("type 1250000/2500000/0 for none", toast_of(s.do("set_level", text="1250000/2500000")))


class Rob2ButtonMidHand(unittest.TestCase):
    """ROB-2: a button move never folds hero or rewrites a hand that has an action."""

    def test_rob_2_the_reviewers_hand(self):
        s = tournament(size=6, level="50/100/0", button=5, stacks=[10000, 9000, 8000, 7000, 6000, 5000])
        s.do("deal", hero_cards="AhKh")                 # hero is the big blind
        play(s, "2 raise 250, 4 call")
        view = s.view()
        self.assertTrue(view["hand"]["target_is_hero"])
        before = json.dumps(view["hand"]["line"])
        self.assertIn("discard the hand", refused(s, "set_button", seat=2).fix)
        self.assertTrue(refused(s, "button_step", step=1).message)
        view = s.view()
        self.assertEqual(json.dumps(view["hand"]["line"]), before)
        self.assertFalse(view["table"]["seats"][0]["folded"])
        self.assertTrue(view["hand"]["target_is_hero"])

    def test_rob_2_after_undo_or_discard_the_button_moves(self):
        s = tournament(size=6, button=5)
        s.do("deal")
        play(s, "2 raise 500")
        s.do("undo")
        self.assertEqual(s.do("set_button", seat=2)["table"]["button"], 2)
        play(s, "5 raise 500")
        s.do("discard_hand")
        self.assertEqual(s.do("button_step", step=1)["table"]["button"], 3)


class Rob9Requests(unittest.TestCase):
    """ROB-9: a step is taken round the table, names and notes have a length, a refusal has no Python in it."""

    def test_rob_9_a_huge_button_step_is_a_few_steps(self):
        s = tournament(size=6)
        self.assertEqual(s.do("button_step", step=6 * 10 ** 6 + 2)["table"]["button"], 3)
        self.assertEqual(s.do("button_step", step=-(6 * 10 ** 6 + 2))["table"]["button"], 1)
        for step in (1e12, float("inf"), "x", [1]):
            self.assertIn("could not be read", refused(s, "button_step", step=step).message)

    def test_rob_9_names_and_notes_are_cut(self):
        s = tournament(size=6)
        view = s.do("rename", seat=2, name="N" * 900000)
        self.assertEqual(len(view["table"]["seats"][1]["name"]), 40)
        view = s.do("note", seat=2, text="x" * 900000)
        self.assertEqual(len(view["table"]["seats"][1]["note"]), 500)
        view = s.do("seat_player", seat=3, name="  Long   name\nwith a line break " + "y" * 100)
        self.assertEqual(view["table"]["seats"][2]["name"][:28], "Long name with a line break ")
        self.assertEqual(len(view["table"]["seats"][2]["name"]), 40)
        self.assertLessEqual(len(s.do("set_tournament", name="T" * 500)["strip"]["name"]), 80)

    def test_rob_9_a_refusal_holds_no_python_text(self):
        s = tournament(size=6)
        s.do("deal")
        for op, args in (("button_step", {"step": "x"}), ("set_size", {"size": "x"}), ("set_size", {"delta": [1]}),
                         ("close_round", {"callers": 7}), ("award", {"ranking": 5}), ("set_stacks", {"values": {"x": 1}}),
                         ("act", {"seat": [2], "kind": "call"}), ("set_cards", {"shown": {"x": "AhKd"}})):
            err = refused(s, op, **args)
            for word in ("Error", "int()", "object", "literal", "Traceback"):
                self.assertNotIn(word, err.message + err.fix, (op, args))
        self.assertIn("Error", s.last_fault)                        # the detail is kept for the --verbose log


class Rob13NegativeIndex(unittest.TestCase):
    def test_rob_13_a_negative_index_is_refused_like_one_past_the_end(self):
        s = table_a()
        play(s, "4 raise 500, 5 call, 1 raise 1500")
        for op in ("edit_event", "remove_event"):
            for index in (-1, -3, 99, "x", None, 1e999):
                err = refused(s, op, index=index, kind="fold")
                self.assertIn("not on the hand line", err.message, (op, index))
            self.assertIn("not on the hand line", refused(s, op, event=-1, kind="fold").message)


class FilesCase(unittest.TestCase):
    """A folder of its own, a saved tournament in it, and no waiting between the retries."""

    def setUp(self):
        from unittest import mock
        from poker_coach.app import model
        self.model, self.mock = model, mock
        self.folder = tempfile.mkdtemp(prefix="menlo-files-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        for name in ("READ_WAIT", "WRITE_WAIT"):
            patch = mock.patch.object(model, name, 0)
            patch.start()
            self.addCleanup(patch.stop)

    def path(self, name="tournament.json"):
        return os.path.join(self.folder, name)

    def saved_table(self):
        """Bob sits in seat 2 with 23,000; the file before the last change (.bak) has him on 10,000."""
        s = Session(self.folder)
        s.do("new_session", mode="tournament", size=6, start_stack=10000, level="100/200/25", remaining=120, paid=45)
        s.do("rename", seat=2, name="Bob")
        s.do("set_stack", seat=2, text="23k")
        return s

    def bob(self, session):
        seat = session.view()["table"]["seats"][1]
        return seat["name"], seat["stack"]

    def aside(self, name="tournament.json"):
        return sorted(n for n in os.listdir(self.folder) if n.startswith(name + ".unreadable-"))

    def held(self, *names, times=None):
        """``open`` as Windows answers while another program holds these files (``times``: only so often)."""
        real, left = open, {"n": times}

        def fake(path, *args, **kwargs):
            if os.path.basename(str(path)) in names and "r" in (args[0] if args else kwargs.get("mode", "r")):
                if left["n"] is None or left["n"] > 0:
                    left["n"] = None if left["n"] is None else left["n"] - 1
                    raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(path, *args, **kwargs)
        return self.mock.patch("builtins.open", fake)


class PackageSavingA(FilesCase):
    """package.md (a): a save that fails is tried again; if it still fails the change is made, not refused."""

    def refusing_replace(self, times):
        real, calls = os.replace, {"n": 0}

        def fake(src, dst):
            if str(src).endswith(".tmp"):
                calls["n"] += 1
                if times is None or calls["n"] <= times:
                    raise PermissionError(13, "Access is denied")
            return real(src, dst)
        return self.mock.patch.object(self.model.os, "replace", fake), calls

    def test_package_a_a_held_file_is_tried_again(self):
        s = self.saved_table()
        patch, calls = self.refusing_replace(times=4)               # the antivirus lets go after a moment
        with patch:
            view = s.do("rename", seat=3, name="Cy")
        self.assertEqual((view["unsaved"], calls["n"]), ("", 6))     # four refusals, then both files
        self.assertEqual(Session(self.folder).view()["table"]["seats"][2]["name"], "Cy")

    def test_package_a_made_not_saved_yet_and_saved_with_the_next_change(self):
        s = self.saved_table()
        rev = s.rev
        patch, calls = self.refusing_replace(times=None)
        with patch:
            view = s.do("rename", seat=3, name="Cy")                # accepted: the change is made
            self.assertEqual((view["rev"], view["table"]["seats"][2]["name"]), (rev + 1, "Cy"))
            self.assertIn("Made, not saved yet", toast_of(view))
            self.assertTrue(view["unsaved"])
            self.assertEqual(calls["n"], 2 * self.model.WRITE_TRIES)           # both files, ten tries each
            self.assertTrue(s.view()["unsaved"])                    # a plain view says so too
        self.assertEqual(Session(self.folder).view()["table"]["seats"][2]["name"], "")     # not on disk yet
        self.assertFalse([n for n in os.listdir(self.folder) if n.endswith(".tmp")])
        view = s.do("rename", seat=4, name="Di")                    # the next change saves both
        self.assertEqual((view["unsaved"], toast_of(view)), ("", ""))
        names = [seat["name"] for seat in Session(self.folder).view()["table"]["seats"]]
        self.assertEqual(names[2:4], ["Cy", "Di"])
        self.assertEqual(Session(self.folder).rev, s.rev)

    def test_package_a_a_folder_that_cannot_be_written_keeps_the_change_in_memory(self):
        s = Session(self.path("a file") + os.sep + "below")         # a folder that cannot be made
        with open(self.path("a file"), "w") as fh:
            fh.write("x")
        view = s.do("new_session")
        self.assertIn("not saved yet", toast_of(view))
        self.assertFalse(view["first_run"])

    def test_rob_3_the_temporary_file_has_a_name_of_its_own(self):
        s = self.saved_table()
        seen = []
        real = os.replace
        with self.mock.patch.object(self.model.os, "replace", lambda a, b: (seen.append(os.path.basename(a)), real(a, b))[1]):
            s.do("rename", seat=3, name="Cy")
        self.assertIn(f"tournament.json.{os.getpid()}.tmp", seen)
        with open(self.path("tournament.json.999.tmp"), "w") as fh:  # left by a program that was killed long ago
            fh.write("{half")
        os.utime(self.path("tournament.json.999.tmp"), (1, 1))
        Session(self.folder)
        self.assertFalse([n for n in os.listdir(self.folder) if n.endswith(".tmp")])


class PackageSavingB(FilesCase):
    """package.md (b) and ROB-4: a file that is only held is never treated as a damaged one."""

    def test_package_b_a_held_file_is_tried_again(self):
        self.saved_table()
        with self.held("tournament.json", times=3):
            again = Session(self.folder)
        self.assertEqual(self.bob(again), ("Bob", 23000))
        self.assertIsNone(again.view()["toast"])

    def test_package_b_a_file_held_for_good_stops_the_start_and_nothing_is_renamed(self):
        self.saved_table()
        before = sorted(os.listdir(self.folder))
        with self.held("tournament.json"):
            with self.assertRaises(OSError) as caught:
                Session(self.folder)
        self.assertIn("Close the program that holds the file", str(caught.exception))
        self.assertIn("tournament.json", str(caught.exception))
        self.assertEqual(sorted(os.listdir(self.folder)), before)
        self.assertEqual(self.bob(Session(self.folder)), ("Bob", 23000))    # the table is there when the file is free

    def test_rob_4_the_reviewers_case_with_real_permissions(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("needs a user the file system can refuse")
        self.saved_table()
        os.chmod(self.path(), 0)
        self.addCleanup(os.chmod, self.path(), 0o644)
        with self.assertRaises(OSError):
            Session(self.folder)
        self.assertEqual(self.aside(), [])


class PackageSavingC(FilesCase):
    """package.md (c): a mode whose file cannot be read is not switched to, and nothing is half switched."""

    def test_package_c_set_mode_changes_nothing_when_the_other_file_is_held(self):
        s = self.saved_table()
        s.do("set_mode", mode="spin")
        s.do("new_session", mode="spin")
        s.do("deal", hero_cards="AsKs")
        again = Session(self.folder)                                # spin is on screen; the tournament is on disk
        with self.held("tournament.json"):
            err = refused(again, "set_mode", mode="tournament")
            self.assertIn("cannot be read right now", err.message)
            self.assertIn("then try again", err.fix)
            self.assertNotIn("Error", err.message + err.fix)
            self.assertEqual((again.view()["mode"], again.data["mode"], again.app["mode"]), ("spin", "spin", "spin"))
            again.do("act", kind="fold")                            # the next change is saved as a Spin table
        with open(self.path("spin.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["mode"], "spin")
        with open(self.path(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["table"]["seats"]["2"]["name"], "Bob")
        Session(self.folder).do("set_mode", mode="tournament")     # once the file is free, the mode is there again
        self.assertEqual(self.bob(Session(self.folder)), ("Bob", 23000))
        self.assertEqual(self.aside("tournament.json") + self.aside("spin.json"), [])


class Rob4DamagedFiles(FilesCase):
    """ROB-4: a damaged file is kept under a dated name, the user is told, and the last good save comes back."""

    def damage(self, raw: bytes, name="tournament.json", bak=True):
        with open(self.path(name), "wb") as fh:
            fh.write(raw)
        if not bak and os.path.exists(self.path(name + ".bak")):
            os.remove(self.path(name + ".bak"))

    def test_rob_4_the_copy_of_one_change_earlier_comes_back(self):
        self.saved_table()
        with open(self.path(), "rb") as fh:
            good = fh.read()
        for raw in (good[:len(good) // 2], good[:-1], b"", b"\x00" * 1000, b"\xff\xfe\x00\x01garbage", b"null"):
            self.damage(raw)
            again = Session(self.folder)
            view = again.view()
            self.assertEqual(self.bob(again), ("Bob", 10000), raw[:20])          # the stack of one change earlier
            self.assertIn("tournament.json could not be read and was set aside as tournament.json.unreadable-",
                          toast_of(view))
            self.assertIn("one change earlier", toast_of(view))
            self.assertEqual(toast_of(again.view()), toast_of(view))            # told until the first change
            after = again.do("set_stack", seat=2, text="23k")
            self.assertIn("set aside", toast_of(after))                         # once more, with the first change
            self.assertIsNone(again.view()["toast"])
            self.assertEqual(self.bob(Session(self.folder)), ("Bob", 23000))    # and the main file is written again
        self.assertEqual(toast_of(again.do("rename", seat=3, name="Cy")), "")   # the news is not told a third time
        self.assertEqual(len(self.aside()), 6)                                  # never over an older one
        with open(self.path(self.aside()[0]), "rb") as fh:
            self.assertEqual(fh.read(), good[:len(good) // 2])

    def test_rob_4_without_a_copy_it_is_a_new_table_and_the_user_is_told(self):
        self.saved_table()
        self.damage(b"{not json", bak=False)
        again = Session(self.folder)
        view = again.view()
        self.assertTrue(view["first_run"])
        self.assertIn("set aside as tournament.json.unreadable-", toast_of(view))
        self.assertIn("This is a new table", toast_of(view))
        self.damage(b"{not json", bak=False)
        Session(self.folder)                                        # a second bad start: the first file stays
        self.assertEqual(len(self.aside()), 2)

    def test_a_damaged_app_json_is_not_called_a_new_table(self):
        """app.json holds the mode on screen, the unit and the deck.  When it was damaged the notice said
        "This is a new table" although every table was back as it had been."""
        self.saved_table()
        with open(self.path("app.json"), "w", encoding="utf-8") as fh:
            fh.write("not json")
        again = Session(self.folder)
        view = again.view()
        self.assertEqual((view["first_run"], self.bob(again)), (False, ("Bob", 23000)))     # the table is there
        said = toast_of(view)
        self.assertIn("app.json could not be read and was set aside as app.json.unreadable-", said)
        self.assertIn("Your tables are as they were", said)
        self.assertNotIn("new table", said)

    def test_rob_4_a_byte_order_mark_is_not_damage(self):
        self.saved_table()
        with open(self.path(), "rb") as fh:
            good = fh.read()
        self.damage(b"\xef\xbb\xbf" + good)
        again = Session(self.folder)
        self.assertEqual((self.bob(again), again.view()["toast"], self.aside()), (("Bob", 23000), None, []))

    def test_rob_4_a_missing_main_file_uses_the_copy(self):
        self.saved_table()
        os.remove(self.path())
        again = Session(self.folder)
        self.assertEqual(self.bob(again), ("Bob", 10000))
        self.assertIn("tournament.json was missing", toast_of(again.view()))

    def test_rob_4_the_saved_copy_is_the_file_before_the_last_change(self):
        s = self.saved_table()
        with open(self.path("tournament.json.bak"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["table"]["seats"]["2"]["stack"], 10000)
        s.do("rename", seat=2, name="Rob")
        with open(self.path("tournament.json.bak"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["table"]["seats"]["2"]["name"], "Bob")


class Rob8WrongShape(FilesCase):
    """ROB-8: a file that is JSON but not a session is set aside like a damaged one; small gaps are filled."""

    def saved(self, name="tournament.json"):
        with open(self.path(name), encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, content, name="tournament.json"):
        with open(self.path(name), "w", encoding="utf-8") as fh:
            json.dump(content, fh)
        if os.path.exists(self.path(name + ".bak")):
            os.remove(self.path(name + ".bak"))

    def test_rob_8_not_a_session_at_all(self):
        self.saved_table()
        for content in ([1, 2, 3], 5, "hello", {}, {"mode": "spin"}, {"mode": "tournament", "table": 7},
                        {"mode": "tournament", "hands": {}}):
            self.write(content)
            again = Session(self.folder)
            view = again.view()
            self.assertTrue(view["first_run"], content)
            self.assertIn("set aside", toast_of(view), content)
            again.do("new_session")
        self.assertEqual(len(self.aside()), 7)

    def test_rob_8_app_json_of_the_wrong_shape(self):
        self.saved_table()
        for content in ([1, 2], "x", 7):
            self.write(content, "app.json")
            again = Session(self.folder)
            self.assertEqual(self.bob(again), ("Bob", 23000), content)
            self.assertIn("app.json could not be read", toast_of(again.view()))
            again.do("rename", seat=2, name="Bob")
        self.write({"mode": "cash", "unit": 5, "deck": None, "rev": "x", "notice_seen": "yes", "more": 1}, "app.json")
        again = Session(self.folder)                                # wrong values: the defaults, without a word
        self.assertEqual((again.app["mode"], again.app["unit"], again.rev, again.view()["toast"]),
                         ("tournament", "chips", 0, None))

    def test_rob_8_what_a_later_version_adds_is_filled_in(self):
        s = self.saved_table()
        s.do("deal", hero_cards="AhKh")
        s.do("act", seat=4, kind="raise", amount=500)
        data = self.saved()
        for seat in data["table"]["seats"].values():
            for key in ("stale", "note", "type"):
                del seat[key]
        for key in ("shown", "settled", "leaving", "advice", "skipped"):
            del data["hand"][key]
        del data["config"]["style"], data["rules"]["short_post"], data["tally"]
        del data["table"]["seats"]["1"]
        self.write(data)
        again = Session(self.folder)
        view = again.view()
        self.assertEqual((self.bob(again), view["toast"], self.aside()), (("Bob", 22875), None, []))   # he posted 125
        self.assertEqual((view["hand"]["line"][-1]["text"], view["strip"]["style"]), ("LJ raise 2.5bb", "survive"))
        again.do("act", kind="call")

    def test_rob_8_a_session_that_cannot_be_drawn_is_set_aside(self):
        s = self.saved_table()
        s.do("deal", hero_cards="AhKh")
        good = self.saved()

        def broken(change):
            data = copy.deepcopy(good)
            change(data)
            return data

        cases = {
            "table.size as text": lambda d: d["table"].update(size="8"),
            "level index past the ladder": lambda d: d["structure"].update(index=999),
            "players left as a word": lambda d: d["tournament"].update(remaining="many"),
            "a stack of null": lambda d: d["table"]["seats"]["2"].update(stack=None),
            "a hand with a big blind of zero": lambda d: d["hand"]["level"].update(bb=0),
            "a hand without its players": lambda d: d["hand"].pop("order"),
            "a stack that is not a number": lambda d: d["table"]["seats"]["3"].update(stack=float("nan")),
        }
        for label, change in cases.items():
            self.write(broken(change))
            again = Session(self.folder)                            # it starts ...
            view = again.view()                                     # ... and every view works
            self.assertTrue(view["first_run"], label)
            self.assertIn("could not be read and was set aside", toast_of(view), label)
            json.dumps(view, allow_nan=False)
        self.assertEqual(len(self.aside()), len(cases))

    def test_rob_8_a_broken_undo_history_costs_the_history_only(self):
        self.saved_table()
        data = self.saved()
        data["journal"] = {"undo": [5, None], "redo": "x"}
        self.write(data)
        again = Session(self.folder)
        self.assertEqual((self.bob(again), again.view()["can"]), (("Bob", 23000), {"undo": False, "redo": False}))


class Rob5NothingUnshowableIsSaved(FilesCase):
    """ROB-5: the view is built before the save; a change that breaks it is refused and leaves no trace."""

    def test_rob_5_a_change_that_breaks_the_view_is_put_back(self):
        s = self.saved_table()
        with open(self.path(), "rb") as fh:
            on_disk = fh.read()

        def slip(a):                                                # a fault of the program: a stack that is no number
            s.data["table"]["seats"]["2"]["stack"] = float("nan")

        with self.mock.patch.object(s, "_op_rename", slip):
            err = refused(s, "rename", seat=2, name="x")
        self.assertIn("was not made", err.message)
        self.assertNotIn("nan", err.message + err.fix)
        with open(self.path(), "rb") as fh:
            self.assertEqual(fh.read(), on_disk)
        json.dumps(s.view(), allow_nan=False)
        self.assertEqual(self.bob(Session(self.folder)), ("Bob", 23000))

    def test_rob_5_two_huge_stacks_all_in(self):
        s = tournament(size=3)
        self.assertTrue(refused(s, "set_stacks", values=[1e308, 1e308, 1000]).message)
        s.do("set_stacks", values=[10 ** 12, 10 ** 12, 1000])
        s.do("deal")
        play(s, "1 allin, 2 call")
        s.do("close_round")
        json.dumps(s.view(), allow_nan=False)


class Ops5UndoStopsAtTheFirstTable(unittest.TestCase):
    """OPS-5 (contract 3): undo never goes back to the set-up form; a tournament over an old one still can be undone."""

    def test_ops_5_undo_stops_at_the_first_table(self):
        s = Session(save=False)
        self.assertTrue(s.view()["first_run"])
        view = s.do("new_session", mode="tournament", size=8, level="300/600/75", hero_stack=12900, remaining=96, paid=75)
        self.assertEqual((view["first_run"], view["can"]), (False, {"undo": False, "redo": False}))
        self.assertIn("first", refused(s, "undo").fix + refused(s, "undo").message + " first")
        s.do("deal", hero_cards="72o")
        s.do("act", kind="fold")
        s.do("close_round")
        presses = 0
        while s.view()["can"]["undo"]:
            view = s.do("undo")
            presses += 1
        self.assertEqual(presses, 3)
        self.assertEqual((view["first_run"], view["strip"]["remaining"], stack(s, 1)), (False, 96, 12900))
        self.assertEqual(refused(s, "undo").message, "There is nothing to undo.")
        self.assertTrue(s.view()["can"]["redo"])                    # and everything can be redone from there
        for _ in range(3):
            view = s.do("redo")
        self.assertEqual(len(view["history"]), 1)

    def test_ops_5_a_new_tournament_over_an_old_one_is_undone_as_before(self):
        s = table_a()
        s.do("close_round")
        s.do("new_session", size=4)
        view = s.do("undo")
        self.assertEqual((view["table"]["size"], len(view["history"]), view["first_run"]), (6, 1, False))

    def test_ops_5_each_mode_stops_at_its_own_first_table(self):
        s = Session(save=False)
        s.do("new_session", mode="tournament")
        s.do("rename", seat=2, name="Al")
        view = s.do("new_session", mode="spin")
        self.assertEqual((view["mode"], view["can"]["undo"]), ("spin", False))
        self.assertTrue(s.do("set_mode", mode="tournament")["can"]["undo"])

    def test_ops_5_a_file_saved_by_the_version_before_loses_the_step_to_the_form(self):
        folder = tempfile.mkdtemp(prefix="menlo-undo-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        s = Session(folder)
        s.do("new_session")
        s.do("rename", seat=2, name="Al")
        path = os.path.join(folder, "tournament.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        first = json.loads(data["journal"]["undo"][0])
        first["started"] = False                                    # what the version before kept: the form itself
        data["journal"]["undo"].insert(0, json.dumps(first, separators=(",", ":")))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        again = Session(folder)
        again.do("undo")
        self.assertEqual(again.view()["can"]["undo"], False)
        self.assertFalse(again.view()["first_run"])

    def test_vis_17_the_button_beside_undone_is_redo(self):
        s = table_a()
        view = s.do("undo")
        self.assertEqual((view["toast"]["text"], view["toast"]["redo"], view["toast"]["undo"]), ("Undone", True, False))
        view = s.do("redo")
        self.assertEqual((view["toast"]["text"], view["toast"]["redo"], view["toast"]["undo"]), ("Redone", False, True))


class Ops13SmallerTable(unittest.TestCase):
    """OPS-13 (contract 4): a smaller table in one step; the players above the new size moved away."""

    def test_ops_13_empty_seats_above_the_new_size_just_go(self):
        s = tournament(size=8, remaining=96)
        s.do("clear_seat", seat=8)
        s.do("clear_seat", seat=7)
        view = s.do("set_size", size=6)
        self.assertEqual((view["table"]["size"], len(view["table"]["seats"]), toast_of(view)), (6, 6, ""))

    def test_ops_13_taken_seats_are_refused_with_a_code_and_cleared_on_request(self):
        s = tournament(size=8, remaining=96, button=8)
        err = refused(s, "set_size", delta=-1)
        self.assertEqual((err.code, err.message), ("seats_taken", "Seat 8 is taken."))
        err = refused(s, "set_size", size=6)
        self.assertEqual(err.message, "Seat 7 and seat 8 are taken.")
        view = s.do("set_size", size=6, clear=True)
        self.assertEqual((view["table"]["size"], [x["seat"] for x in view["table"]["seats"]]), (6, [1, 2, 3, 4, 5, 6]))
        self.assertEqual(view["strip"]["remaining"], 96)            # they moved away: nobody busted
        self.assertIn("2 players moved away", toast_of(view))
        self.assertLessEqual(view["table"]["button"], 6)
        s.do("undo")
        self.assertEqual(s.view()["table"]["size"], 8)

    def test_ops_13_a_hand_nobody_acted_in_is_dealt_again_and_one_under_way_is_protected(self):
        s = tournament(size=8)
        s.do("deal")
        view = s.do("set_size", size=6, clear=True)
        self.assertEqual((view["hand"]["no"], len(state(s).order)), (1, 6))
        s.do("set_size", size=8)
        s.do("seat_player", seat=8, stack=5000)
        s.do("discard_hand")
        s.do("deal")
        play(s, "8 raise 500")
        err = refused(s, "set_size", size=6, clear=True)
        self.assertIn("in the hand being played", err.message)
        self.assertIn("Finish or discard", err.fix)

    def test_ops_13_new_table_takes_size_and_button(self):
        s = tournament(size=8, remaining=96)
        view = s.do("new_table", size=6, button=4)
        self.assertEqual((view["table"]["size"], view["table"]["button"], len(view["table"]["seats"])), (6, 4, 6))
        self.assertEqual(view["strip"]["remaining"], 96)


class Post6ClassHand(unittest.TestCase):
    """POST-6 (contract 2): with AKs on record, cards meant for the flop never become hero's hand."""

    def to_the_flop(self):
        s = tournament(size=6, level="100/200/25")
        s.do("deal", hero_cards="AKs")
        s.do("act", kind="raise", amount=500)
        s.do("act", seat=3, kind="call")                           # the big blind calls: the flop
        return s

    def test_post_6_the_reviewers_keys(self):
        s = self.to_the_flop()
        view = s.view()
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"], view["hand"]["hero_class"]), ("flop", "cards", "AKs"))
        self.assertEqual(view["hand"]["want_suits"],
                         {"hand": "AKs", "options": [["As", "Ks"], ["Ah", "Kh"], ["Ad", "Kd"], ["Ac", "Kc"]]})
        err = refused(s, "set_cards", slot="hero", text="Ks7d")     # the first two flop cards, typed into the prompt
        self.assertEqual(err.code, "class_mismatch")
        self.assertIn("not AKs", err.message)
        self.assertIn("suits", err.fix)
        self.assertEqual(refused(s, "set_cards", hero="Ks7d").code, "class_mismatch")
        self.assertEqual(refused(s, "set_cards", hero="AhKd").code, "class_mismatch")   # ace-king, but not suited
        self.assertEqual(refused(s, "set_cards", hero="AQs").code, "class_mismatch")
        view = s.do("set_cards", text="Ks7d2c")                     # no slot: three cards are the flop
        self.assertEqual((view["hand"]["board"], view["hand"]["hero_class"], view["hand"]["hero_cards"]),
                         (["Ks", "7d", "2c"], "AKs", []))
        self.assertEqual(view["hand"]["needs"], "cards")            # the suits are still wanted
        self.assertEqual(view["hand"]["want_suits"]["options"], [["Ah", "Kh"], ["Ad", "Kd"], ["Ac", "Kc"]])
        self.assertIn("used twice", refused(s, "set_cards", hero="AsKs").message)
        view = s.do("set_cards", slot="hero", text="AhKh")
        self.assertEqual((view["hand"]["hero_cards"], view["hand"]["needs"], view["hand"]["want_suits"]),
                         (["Ah", "Kh"], "action", None))

    def test_post_6_cards_without_a_slot_go_to_the_board_unless_they_are_the_hand(self):
        s = self.to_the_flop()
        view = s.do("set_cards", text="AdKd")                       # the very hand: hero's suits
        self.assertEqual((view["hand"]["hero_cards"], view["hand"]["needs"]), (["Ad", "Kd"], "board"))
        s = self.to_the_flop()
        self.assertIn("does not fit the board", refused(s, "set_cards", text="Ks7d").message)   # two cards are no flop
        self.assertEqual(s.view()["hand"]["hero_class"], "AKs")

    def test_post_6_replace_changes_the_hand_itself(self):
        s = tournament(size=6)
        s.do("deal", hero_cards="AKs")
        self.assertIsNone(s.view()["hand"]["want_suits"])           # before the flop the class is enough
        self.assertEqual(refused(s, "set_cards", hero="AQs").code, "class_mismatch")
        self.assertEqual(s.do("set_cards", hero="AQs", replace=True)["hand"]["hero_class"], "AQs")
        self.assertEqual(s.do("set_cards", hero="AsQs")["hand"]["hero_cards"], ["As", "Qs"])    # its own suits: fine
        self.assertEqual(s.do("set_cards", hero="7h7d")["hand"]["hero_class"], "77")       # exact cards: replaced freely
        self.assertEqual(s.do("set_cards", hero="")["hand"]["hero_class"], "")

    def test_post_6_pairs_and_offsuit_hands(self):
        for cards, count in (("77", 6), ("AKo", 12)):
            s = tournament(size=6)
            s.do("deal", hero_cards=cards)
            s.do("act", kind="raise", amount=500)
            s.do("act", seat=3, kind="call")
            view = s.do("set_cards", text="7s2d2c")
            options = view["hand"]["want_suits"]["options"]
            blocked = 3 if cards == "77" else 0
            self.assertEqual(len(options), count - blocked, cards)
            self.assertTrue(all("7s" not in pair for pair in options))
            s.do("set_cards", hero="".join(options[0]))
            self.assertEqual(s.view()["hand"]["needs"], "action")


def lose_everything(s, losers, winner):
    """Deal a hand in which ``losers`` go all-in and lose to ``winner`` (who covers them); everybody else folds."""
    s.do("deal")
    for seat in state(s).order:
        s.do("act", seat=seat, kind="allin" if seat in losers or seat == winner else "fold")
    return s.do("award", ranking=[[winner]])


def positions(view) -> dict:
    """{position: seat} of the table between hands."""
    return {x["pos"]: x["seat"] for x in view["table"]["seats"] if x["pos"]}


class Ops12ButtonAfterABust(unittest.TestCase):
    """OPS-12 and ROB-11 (contract 1): the big blind moves on by one player whoever went out.

    The button may rest on an empty seat (a dead button).
    """

    def six(self, **fields):
        """Button on hero (seat 1), small blind seat 2, big blind seat 3; seat 5 covers everybody."""
        return tournament(size=6, stacks=[10000, 10000, 10000, 10000, 50000, 10000], remaining=60, **fields)

    def test_ops_12_the_usual_move(self):
        s = self.six()
        s.do("deal")
        view = s.do("close_round")                                  # a walk: nobody out
        self.assertEqual((view["table"]["button"], positions(view)["SB"], positions(view)["BB"]), (2, 3, 4))
        self.assertNotIn("utton", toast_of(view))
        self.assertEqual(view["settings"]["button_rule"], "dead")   # the default
        self.assertEqual(view["strip"]["button_rule"], "dead")

    def test_ops_12_the_small_blind_goes_out(self):
        s = self.six()
        view = lose_everything(s, [2], 5)
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["SB"], where["BB"], where["BTN"]), (2, 3, 4, 1))
        seat_2 = view["table"]["seats"][1]
        self.assertEqual((seat_2["empty"], seat_2["is_button"]), (True, True))         # a dead button
        self.assertIn("Dead button on seat 2", toast_of(view))
        self.assertIn("[ and ] move it", toast_of(view))
        s.do("deal")
        self.assertEqual((state(s).blind[3], state(s).blind[4]), (100, 200))
        self.assertEqual(state(s).order[-3], 1)                     # hero acts last before the blinds
        view = s.do("close_round")
        self.assertEqual((view["table"]["button"], positions(view)["SB"], positions(view)["BB"]), (3, 4, 5))

    def test_ops_12_the_reviewers_side_pot_hand(self):
        s = tournament(size=8, stacks=[5000, 10000, 20000] + [20000] * 5, level="300/600/75")
        s.do("deal")
        play(s, "1 allin, 2 allin, 3 call")
        view = s.do("award", ranking=[[1], [3]])                    # hero wins the main pot, seat 3 the side pot
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["SB"], where["BB"], where["BTN"]), (2, 3, 4, 1))

    def test_ops_12_the_big_blind_goes_out(self):
        s = self.six()
        view = lose_everything(s, [3], 5)
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["SB"], where["BB"]), (1, 2, 4))    # the big blind is seat 4's
        self.assertIn("Button on seat 1: check it against your table", toast_of(view))
        self.assertIn("[ and ] move it", toast_of(view))
        s.do("deal")
        self.assertEqual(state(s).blind[4], 200)

    def test_ops_12_both_blinds_go_out(self):
        s = self.six()
        view = lose_everything(s, [2, 3], 5)
        where = positions(view)
        self.assertEqual((where["BB"], where["SB"], where["BTN"], view["table"]["button"]), (4, 1, 6, 6))
        self.assertIn("check it against your table", toast_of(view))

    def test_ops_12_a_bust_elsewhere(self):
        for loser, big in ((6, 4), (1, 4),                          # a player elsewhere, the button himself
                           (4, 5)):                                 # the player the big blind was coming to
            s = self.six()
            view = lose_everything(s, [loser], 5)
            where = positions(view)
            self.assertEqual((view["table"]["button"], where["SB"], where["BB"]), (2, 3, big), loser)
            self.assertNotIn("utton", toast_of(view), loser)

    def test_ops_12_three_players_to_two_in_each_of_the_three_ways(self):
        for out, button, small, big in ((1, 3, 3, 2),               # the button goes out
                                        (2, 3, 3, 1),               # the small blind goes out
                                        (3, 2, 2, 1)):              # the big blind goes out
            winner = 1 if out != 1 else 2
            stacks = [10000] * 3
            stacks[winner - 1] = 50000
            s = tournament(size=3, stacks=stacks)                   # button 1, small blind 2, big blind 3
            s.do("deal")
            self.assertEqual(state(s).order[-1], 3)
            s.do("discard_hand")
            view = lose_everything(s, [out], winner)
            where = positions(view)
            self.assertEqual((view["table"]["button"], where["BTN/SB"], where["BB"]), (button, small, big), out)
            self.assertNotEqual(where["BB"], 3, "the same player would post the big blind twice in a row")
            s.do("deal")
            st = state(s)
            self.assertEqual((st.blind[small], st.blind[big], st.order), (100, 200, [small, big]), out)

    def test_ops_12_spin_the_button_goes_out_and_hero_does_not_post_the_big_blind_twice(self):
        s = spin(stacks={1: 400, 2: 100, 3: 400}, button=2)         # hero is the big blind
        self.assertEqual(state(s).labels[1], "BB")
        play(s, "2 allin, 3 fold, 1 call")
        view = s.do("award", winner=1)
        where = positions(view)
        self.assertEqual((where["BTN/SB"], where["BB"]), (1, 3))

    def test_ops_12_the_forward_setting(self):
        s = self.six()
        view = s.do("set_config", button_rule="forward")
        self.assertEqual((view["settings"]["button_rule"], view["can"]["undo"]), ("forward", True))
        view = lose_everything(s, [2], 5)
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["SB"], where["BB"]), (3, 4, 5))    # as before this round
        self.assertIn("Button on seat 3: check it against your table", toast_of(view))
        s = self.six(button=1)
        s.do("set_config", button_rule="forward")
        view = lose_everything(s, [3], 5)
        self.assertEqual((view["table"]["button"], positions(view)["SB"], positions(view)["BB"]), (2, 4, 5))
        self.assertIn("button", refused(s, "set_config", button_rule="sideways").message)
        self.assertEqual(s.do("set_config", button_rule="")["settings"]["button_rule"], "dead")    # no value: the other one

    def test_ops_12_a_bust_typed_after_the_hand_moves_the_button_the_same_way(self):
        s = self.six()
        s.do("deal")
        view = s.do("skip_hand")                                    # the result was not recorded
        self.assertEqual(view["table"]["button"], 2)
        view = s.do("bust", seat=2)                                 # the small blind of that hand went out in it
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["SB"], where["BB"], where["BTN"]), (2, 3, 4, 1))
        self.assertIn("Dead button on seat 2", toast_of(view))
        self.assertEqual(view["strip"]["remaining"], 59)
        s = self.six()
        s.do("deal")
        s.do("deal")                                                # N on the open hand, then the bust is noticed
        view = s.do("bust", seat=3)                                 # the big blind of the hand before
        st = state(s)
        self.assertEqual((view["hand"]["no"], st.button, st.order[-2], st.order[-1]), (2, 1, 2, 4))
        self.assertIn("check it against your table", toast_of(view))
        view = s.do("button_step", step=1)                          # the user's table has it one seat on
        self.assertEqual(view["table"]["button"], 2)
        view = s.do("clear_seat", seat=6)                           # set by hand: it stays where it was put
        self.assertEqual(view["table"]["button"], 2)

    def test_ops_12_the_button_can_be_put_on_an_empty_seat(self):
        s = self.six()
        s.do("clear_seat", seat=2)
        view = s.do("set_button", seat=2)
        where = positions(view)
        self.assertEqual((view["table"]["button"], where["BTN"], where["SB"], where["BB"]), (2, 1, 3, 4))
        self.assertTrue(view["table"]["seats"][1]["is_button"] and view["table"]["seats"][1]["empty"])
        self.assertEqual(s.do("button_step", step=1)["table"]["button"], 3)             # ] goes on to the next player
        self.assertEqual(s.do("button_step", step=-1)["table"]["button"], 1)            # [ back to the one before

    def test_ops_12_the_big_blind_always_moves_on_by_one_player(self):
        """Random tables and random busts, in the hand or typed after it: the next big blind is the next player."""
        rng = random.Random(12)
        for trial in range(60):
            size = rng.randint(3, 9)
            s = tournament(size=size, stacks=[10000] * size, button=rng.randint(1, size))
            for hand_no in range(12):
                seats = [x["seat"] for x in s.view()["table"]["seats"] if not x["empty"] and x["stack"] > 0]
                if len(seats) < 2:
                    break
                s.do("deal")
                st = state(s)
                big = st.order[-1]
                out = [seat for seat in seats if rng.random() < 0.25][:len(seats) - 2]
                if out and rng.random() < 0.5:                      # they go out in the hand
                    winner = rng.choice([seat for seat in seats if seat not in out])
                    s.do("set_stack", seat=winner, text=str(10000 * size))
                    for seat in state(s).order:
                        s.do("act", seat=seat, kind="allin" if seat in out or seat == winner else "fold")
                    s.do("award", ranking=[[winner], out])          # (a loser with more chips keeps the rest)
                else:                                               # or the user types the busts afterwards
                    s.do("skip_hand")
                    for seat in out:                                # (hero's stack typed as 0 is the same thing)
                        s.do("bust", seat=seat) if seat != 1 or rng.random() < 0.5 else s.do("set_stack", seat=1, text="0")
                left = sorted(x["seat"] for x in s.view()["table"]["seats"] if not x["empty"] and x["stack"] > 0)
                if len(left) < 2:
                    break
                where = positions(s.view())
                expected = next((seat for seat in left if seat > big), left[0])
                self.assertEqual(where["BB"], expected, (trial, hand_no, out, left))
                if len(left) == 2:
                    self.assertIn("BTN/SB", where)


class Ops16HeroOut(unittest.TestCase):
    """OPS-16 (contract 6): view.hero_out while hero has no chips; a stack typed on his seat then is a re-entry."""

    def busted(self, **fields):
        s = tournament(size=6, stacks=[5000, 10000, 10000, 10000, 20000, 10000], remaining=96, paid=75, entrants=500,
                       **fields)
        s.do("deal", hero_cards="AhKh")
        play(s, "5 raise 500, 1 allin, 5 call")
        self.assertFalse(s.view()["hero_out"])                      # all-in, and his hand is running
        return s, s.do("award", winner=5)

    def test_ops_16_hero_out_is_in_the_view_while_he_has_no_chips(self):
        s, view = self.busted()
        self.assertTrue(view["hero_out"])
        self.assertEqual(view["strip"]["remaining"], 95)
        self.assertIn("You are out. Type a new stack on your seat to re-enter, or start a new tournament.", toast_of(view))
        view = s.do("deal")                                         # N deals a hand without him
        self.assertEqual((view["hero_out"], 1 in state(s).order), (True, False))
        self.assertFalse(tournament().view()["hero_out"])

    def test_ops_16_a_stack_typed_on_his_seat_is_a_re_entry(self):
        s, view = self.busted()
        view = s.do("set_stack", seat=1, text="20000")
        self.assertEqual((view["hero_out"], view["strip"]["remaining"], view["strip"]["entrants"]), (False, 96, 501))
        self.assertEqual(toast_of(view), "Re-entry: players left 96 and entrants 501")
        self.assertEqual(stack(s, 1), 20000)
        view = s.do("set_stack", seat=1, text="19000")              # a correction is not another re-entry
        self.assertEqual((view["strip"]["remaining"], view["strip"]["entrants"], toast_of(view)), (96, 501, ""))
        s.do("undo")
        view = s.do("undo")                                         # one undo step takes the whole re-entry back
        self.assertEqual((view["hero_out"], view["strip"]["remaining"], view["strip"]["entrants"]), (True, 95, 500))

    def test_ops_16_the_other_ways_to_type_it(self):
        s, _ = self.busted()
        view = s.do("seat_player", seat=1, stack="15k")
        self.assertEqual((view["strip"]["remaining"], view["strip"]["entrants"], view["hero_out"]), (96, 501, False))
        s, _ = self.busted()
        view = s.do("set_stacks", values=["15k", "", "", "", "", ""])
        self.assertEqual((view["strip"]["remaining"], view["strip"]["entrants"]), (96, 501))
        s = tournament(size=6, remaining=96, entrants=500)
        s.do("bust", seat=1)                                        # busted by hand
        self.assertTrue(s.view()["hero_out"])
        view = s.do("set_stack", seat=1, text="10000")
        self.assertEqual((view["strip"]["remaining"], view["strip"]["entrants"]), (96, 501))

    def test_ops_16_a_hand_dealt_without_him_is_dealt_again_when_nobody_has_acted(self):
        s, _ = self.busted()
        s.do("deal")
        view = s.do("set_stack", seat=1, text="20000")
        self.assertIn(1, state(s).order)
        self.assertEqual(view["hand"]["no"], 2)
        s, _ = self.busted()
        s.do("deal")
        s.do("act", seat=5, kind="raise", amount=500)
        view = s.do("set_stack", seat=1, text="20000")              # a hand under way: he is in from the next one
        self.assertEqual((1 in state(s).order, view["hero_out"], view["strip"]["entrants"]), (False, False, 501))

    def test_ops_16_without_the_numbers_and_with_a_stack_of_zero_typed(self):
        s = tournament(size=6, stacks=[5000, 10000, 10000, 10000, 20000, 10000])
        s.do("deal")
        play(s, "5 raise 500, 1 allin, 5 call")
        s.do("award", winner=5)
        self.assertEqual(toast_of(s.do("set_stack", seat=1, text="8000")), "Re-entry: you are dealt in again")
        s = tournament(size=6, remaining=96, entrants=500)
        s.do("set_stack", seat=1, text="0")                         # typed, not busted: nobody was counted out
        self.assertTrue(s.view()["hero_out"])
        view = s.do("set_stack", seat=1, text="9000")
        self.assertEqual((view["strip"]["remaining"], view["strip"]["entrants"]), (96, 500))

    def test_vis_17_spin_says_how_the_game_ended(self):
        s = spin(stacks={1: 100, 2: 400, 3: 400})
        play(s, "1 allin, 2 call, 3 fold")
        view = s.do("award", winner=2)
        self.assertEqual(toast_of(view), "You lost this game. Press N for a new one.")
        self.assertTrue(view["hero_out"])
        s = spin(stacks={1: 800, 2: 50, 3: 50})
        play(s, "1 allin, 2 call, 3 call")
        self.assertIn("You won this game. Press N for a new one.", toast_of(s.do("award", winner=1)))

    def test_vis_17_words(self):
        s = Session(save=False)
        view = s.do("new_session", mode="tournament")
        self.assertEqual(toast_of(view), "New tournament started")
        self.assertEqual(view["strip"]["stage"], {"code": "unknown", "label": "ADD LEFT AND PAID"})
        self.assertEqual(s.do("set_tournament", remaining=96)["strip"]["stage"]["label"], "ADD PAID")
        self.assertEqual(s.do("set_tournament", remaining="", paid=75)["strip"]["stage"]["label"], "ADD LEFT")
        self.assertEqual(s.do("set_tournament", remaining=96)["strip"]["stage"]["code"], "approach")
        self.assertIn("Spin & Gold", toast_of(s.do("new_session", mode="spin")))


class Vis1TheFinishedHandKeepsItsNames(unittest.TestCase):
    """VIS-1 and OPS-15 (contract 10): view.hand.positions and view.hand.button are the hand's own, also after it."""

    def test_vis_1_positions_and_button_of_the_hand_on_screen(self):
        s = tournament(size=6, button=1)
        view = s.do("deal")
        names = {"1": "BTN", "2": "SB", "3": "BB", "4": "LJ", "5": "HJ", "6": "CO"}
        self.assertEqual((view["hand"]["positions"], view["hand"]["button"]), (names, 1))
        play(s, "4 raise 500, 1 call, 3 call")
        for street in ("flop", "turn", "river"):                    # checked down
            s.do("close_round")
        view = s.do("award", winner=4)
        self.assertEqual(view["hand"]["needs"], "next")
        self.assertEqual((view["hand"]["positions"], view["hand"]["button"]), (names, 1))      # the hand's own
        self.assertEqual((view["table"]["button"], view["table"]["seats"][0]["pos"]), (2, "CO"))  # the next hand's
        self.assertEqual(view["hand"]["result"]["winners"][0]["pos"], names["4"])
        view = s.do("deal")
        self.assertEqual((view["hand"]["button"], view["hand"]["positions"]["1"]), (2, "CO"))
        json.dumps(view)

    def test_vis_1_a_player_who_went_out_keeps_his_name_in_the_finished_hand(self):
        s = tournament(size=6, stacks=[10000, 2000, 10000, 10000, 10000, 10000])
        s.do("deal")
        play(s, "1 raise 500, 2 allin, 1 call")
        view = s.do("award", winner=1)
        self.assertEqual((view["hand"]["positions"]["2"], view["hand"]["button"]), ("SB", 1))
        self.assertTrue(view["table"]["seats"][1]["empty"])
        self.assertEqual(view["table"]["button"], 2)                # dead button: seat 2 is empty now


def marked(s) -> list:
    """The hand line as text: * an action nobody typed, ~ one that follows from a later action ("he must have called")."""
    return [item["text"] + ("*" if item.get("auto") else "") + ("~" if item.get("inferred") else "")
            for item in s.view()["hand"]["line"]]


def chips(s):
    view = s.view()
    return sum(x["stack"] for x in view["table"]["seats"] if not x["empty"]) + view["hand"]["pot"]


class Rob1ForgottenCaller(unittest.TestCase):
    """ROB-1 and OPS-3: an action typed for a player whose fold was only implied on an earlier street.

    He must have called there: the fold becomes a call on its own street and the typed action
    is recorded on the street being played.  Never is it read as an action of the earlier street.
    """

    def the_reviewers_hand(self):
        """6 seats, 100/200 ante 25, button on hero.  CO raises to 500, hero calls, flop Ks 7d 2c."""
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")                           # the blinds get the implied fold
        self.assertEqual(marked(s)[-3:], ["SB fold*", "BB fold*", "Ks 7d 2c"])
        return s

    def test_rob_1_the_reviewers_hand_a_bet(self):
        s = self.the_reviewers_hand()
        total = chips(s)
        view = s.do("act", seat=3, kind="bet", amount=600)          # the big blind, who had called, leads
        self.assertEqual(toast_of(view), "BB was folded before the flop on the record: now he called there, "
                                         "and bets 600 here. Backspace takes it back.")
        hand = view["hand"]
        self.assertEqual((hand["phase"], hand["to_call"], hand["target_is_hero"], hand["board"]),
                         ("flop", 600, True, ["Ks", "7d", "2c"]))
        self.assertEqual(marked(s), ["AhKh", "LJ fold*", "HJ fold*", "CO raise 2.5bb", "You call", "SB fold*",
                                     "BB call~", "Ks 7d 2c", "BB bet 3bb"])
        self.assertEqual((hand["pot"], chips(s)), (1450 + 300 + 600, total))
        self.assertEqual([e["street"] for e in state(s).log if e["seat"] == 3], ["preflop", "flop"])
        view = s.do("undo")                                         # one step takes both back
        self.assertEqual((marked(s)[-3:], view["hand"]["pot"]), (["SB fold*", "BB fold*", "Ks 7d 2c"], 1450))

    def test_rob_1_a_check(self):
        s = self.the_reviewers_hand()
        view = s.do("act", seat=3, kind="check")
        self.assertIn("now he called there, and checks here", toast_of(view))
        self.assertEqual((marked(s)[-3:], view["hand"]["phase"], view["hand"]["pot"]),
                         (["BB call~", "Ks 7d 2c", "BB check"], "flop", 1750))

    def test_rob_1_an_all_in(self):
        s = self.the_reviewers_hand()
        view = s.do("act", seat=3, kind="allin")
        self.assertIn("now he called there, and moves all-in here", toast_of(view))
        self.assertEqual((view["hand"]["phase"], view["hand"]["to_call"]), ("flop", 19475))
        self.assertEqual(marked(s)[-1], "BB all-in 97.4bb")

    def test_rob_1_a_call_behind_hero_waits_for_hero(self):
        s = self.the_reviewers_hand()
        s.do("act", seat=6, kind="bet", amount=700)                 # hero to act
        err = refused(s, "act", seat=3, kind="call")                # it would be recorded as hero's fold
        self.assertEqual(err.message, "BB folded before the flop on the record.")
        self.assertEqual(err.fix, "Undo to that point, or select that fold on the hand line and change it to a call first.")
        s.do("act", kind="call")                                    # hero calls: the flop is over
        view = s.do("act", seat=3, kind="call")                     # now the forgotten caller fits behind him
        self.assertEqual(marked(s)[-6:], ["BB call~", "Ks 7d 2c", "BB check*", "CO bet 3.5bb", "You call", "BB call"])
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("turn", "board"))

    def test_rob_1_the_cases_that_are_refused(self):
        # a fold that was typed: the hand line is the place to change it
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "5 fold, 6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")
        err = refused(s, "act", seat=5, kind="bet", amount=600)
        self.assertEqual((err.message, err.fix), ("HJ folded before the flop.",
                                                  "Select that fold on the hand line to change it."))
        # the call he must have made would put him all-in: he cannot bet the flop
        s = tournament(size=6, level="100/200/25", stacks=[20000, 20000, 400, 20000, 20000, 20000])
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")
        err = refused(s, "act", seat=3, kind="bet", amount=600)
        self.assertEqual(err.message, "BB folded before the flop on the record.")
        self.assertIn("change it to a call first", err.fix)
        # the typed action itself is not possible on the corrected record: the usual sentence
        s = self.the_reviewers_hand()
        s.do("act", seat=6, kind="bet", amount=700)
        s.do("act", kind="call")                                    # the flop is over; the turn card is wanted
        self.assertIn("cannot check: 700 to call", refused(s, "act", seat=3, kind="check").message)
        # a player who is sitting out
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("set_status", seat=3, status="away")
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")
        self.assertIn("sitting out", refused(s, "act", seat=3, kind="bet", amount=600).message)

    def test_rob_1_folded_twice_on_the_way_he_called_both_times(self):
        s = self.the_reviewers_hand()
        s.do("act", seat=6, kind="bet", amount=700)
        s.do("act", kind="call")
        s.do("set_cards", board="Ks7d2c5h")                         # the turn
        total = chips(s)
        view = s.do("act", seat=3, kind="check")
        self.assertEqual(marked(s)[-7:], ["Ks 7d 2c", "BB check*", "CO bet 3.5bb", "You call", "BB call~", "5h", "BB check"])
        self.assertEqual([e["street"] for e in state(s).log if e["seat"] == 3], ["preflop", "flop", "flop", "turn"])
        self.assertEqual((view["hand"]["phase"], chips(s)), ("turn", total))
        self.assertEqual([(e["kind"], e["to"]) for e in state(s).log if e["seat"] == 1], [("call", 500), ("call", 700)])

    def test_ops_3_the_slip_5_a_on_the_flop(self):
        """Hero raises on the button, the big blind calls, flop: then an all-in is typed for a player passed by."""
        s = tournament(size=8, level="300/600/75", stacks=[20000] * 8)
        s.do("deal", hero_cards="AhKd")
        s.do("act", kind="raise", amount=1200)
        s.do("act", seat=3, kind="call")
        s.do("set_cards", board="Ks7d2c")
        self.assertEqual(s.view()["hand"]["pot"], 3300)
        view = s.do("act", seat=5, kind="allin")
        self.assertIn("UTG+1 was folded before the flop on the record", toast_of(view))
        self.assertNotIn("dropped", toast_of(view))
        hero = [(e["street"], e["kind"], e["to"], e["auto"]) for e in state(s).log if e["seat"] == 1]
        self.assertEqual(hero, [("preflop", "raise", 1200, False)])                 # his raise is as he made it
        self.assertEqual((view["hand"]["phase"], view["hand"]["target_is_hero"], view["hand"]["needs"]),
                         ("flop", True, "action"))                                  # and the decision is still his
        self.assertFalse(view["table"]["seats"][0]["folded"])
        self.assertEqual(marked(s)[-4:], ["UTG+1 call~", "Ks 7d 2c", "BB check*", "UTG+1 all-in 31.2bb"])
        view = s.do("undo")
        self.assertEqual((view["hand"]["pot"], view["hand"]["target_is_hero"]), (3300, True))

    def test_ops_3_a_typed_action_is_never_read_on_another_street(self):
        """Whatever is typed on the flop for a seat that was passed by before it, no pre-flop raise comes of it."""
        for kind, amount in (("bet", 600), ("raise", 1800), ("allin", None), ("check", None), ("call", None), ("fold", None)):
            for seat in (2, 3, 4, 5):
                s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
                s.do("deal", hero_cards="AhKh")
                play(s, "6 raise 500, 1 call")
                s.do("set_cards", board="Ks7d2c")
                try:
                    s.do("act", seat=seat, kind=kind, amount=amount)
                except ModelError:
                    pass
                st = state(s)
                self.assertEqual(st.phase, "flop", (kind, seat))
                self.assertEqual([(e["kind"], e["to"]) for e in st.log if e["street"] == "preflop" and not e["auto"]
                                  and e["seat"] in (6, 1)], [("raise", 500), ("call", 500)], (kind, seat))
                self.assertFalse([e for e in st.log if e["street"] == "preflop" and e["kind"] in ("raise", "bet")
                                  and e["seat"] == seat], (kind, seat))
                self.assertNotIn(1, st.folded)

    def test_ops_3_hero_is_never_dropped_changed_or_folded_by_a_replacement(self):
        s = table_a()                                               # hero on the button
        s.do("set_cards", hero="AKs")
        play(s, "1 raise 500")                                      # 4, 5 and 6 are passed by
        err = refused(s, "act", seat=5, kind="raise", amount=1500)  # a raise in front would undo hero's own
        self.assertIn("your own action", err.message)
        self.assertIn("hand line", err.fix)
        view = s.do("act", seat=5, kind="call")                     # the forgotten limper is fine
        self.assertEqual(marked(s), ["AKs", "LJ fold*", "HJ call", "CO fold*", "You raise 2.5bb"])
        self.assertIsNone(view["toast"])
        s = table_a()
        play(s, "4 raise 500, 1 call")                              # hero called 500
        err = refused(s, "act", seat=5, kind="raise", amount=1500)  # his call would become a call of 1,500
        self.assertIn("your own action", err.message)


class Ops14LateCaller(unittest.TestCase):
    """OPS-14 (contract 5): while the hand waits for cards or a result, a player passed by in the round just closed acts."""

    def test_ops_14_the_late_caller_at_the_showdown(self):
        s = tournament(size=8, level="300/600/75", stacks=[20000] * 8)
        s.do("deal", hero_cards="AhKd")
        play(s, "6 raise 1200, 7 call, 1 raise 4000, 6 call, 7 call")
        s.do("set_cards", board="Ks7d2c")
        play(s, "1 allin, 7 allin")                                 # seat 6 is passed by: an implied fold
        view = s.view()
        self.assertEqual((view["hand"]["needs"], view["hand"]["phase"]), ("result", "showdown"))
        self.assertEqual(len(view["hand"]["pots"][0]["eligible"]), 2)
        view = s.do("act", seat=6, kind="call")
        self.assertEqual(toast_of(view), "Added to the betting on the flop: LJ calls all-in")
        self.assertEqual((view["hand"]["needs"], sorted(view["hand"]["pots"][0]["eligible"])), ("result", [1, 6, 7]))
        self.assertEqual(marked(s)[-3:], ["You all-in 26.5bb", "LJ call all-in", "HJ call all-in"])
        self.assertIn("all-in already", refused(s, "act", seat=6, kind="call").message)
        self.assertIn("The betting is over", refused(s, "act", kind="call").message)

    def test_ops_14_the_late_caller_while_the_flop_is_wanted(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        view = s.do("close_round")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("flop", "board"))
        view = s.do("act", seat=3, kind="call")                     # the big blind had called
        self.assertEqual(toast_of(view), "Added to the betting before the flop: BB calls")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"], view["hand"]["pot"]), ("flop", "board", 1750))
        # a raise is not taken there (T1): it could as well be a bet on the flop.  The fold chip has Raised for it
        self.assertIn("Type the flop first", refused(s, "act", seat=2, kind="raise", amount=2000).message)
        fold = next(item["i"] for item in view["hand"]["line"] if item.get("seat") == 2 and item["verb"] == "fold")
        view = s.do("edit_event", index=fold, kind="raise", amount=2000)        # the small blind had raised
        self.assertEqual((view["hand"]["phase"], view["hand"]["to_call"], view["hand"]["target_is_hero"]),
                         ("preflop", 1500, True))

    def test_ops_14_an_implied_check_can_become_a_bet(self):
        """At the showdown only: while a street's cards are wanted a bet is not taken into the closed round (T1)."""
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c5h9c")                       # checked down to the river
        s.do("close_round")                                         # ... and through it, says Enter
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("showdown", "result"))
        view = s.do("act", seat=6, kind="bet", amount=700)          # no: the cutoff had bet the river
        self.assertIn("Added to the betting on the river: CO bets 700", toast_of(view))
        self.assertEqual((view["hand"]["phase"], view["hand"]["to_call"], view["hand"]["target_is_hero"]),
                         ("river", 700, True))

    def test_ops_14_no_seat_named_is_the_next_street_as_before(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "4 call")
        s.do("close_round")                                         # hero and the blinds take the default
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("flop", "board"))
        view = s.do("act", kind="check")                            # the board is skipped: the action is on the flop
        self.assertEqual((view["hand"]["phase"], state(s).log[-1]["street"], toast_of(view)), ("flop", "flop", ""))

    def test_ops_14_what_was_typed_stays_and_a_typed_fold_names_its_street(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "4 fold, 6 raise 500, 1 call")
        s.do("close_round")
        err = refused(s, "act", seat=4, kind="call")
        self.assertEqual(err.message, "LJ folded.")                 # in the round just closed: no street to name
        s.do("set_cards", board="Ks7d2c")
        self.assertEqual(refused(s, "act", seat=4, kind="call").message, "LJ folded before the flop.")
        view = s.do("act", seat=6, kind="check")                    # a player who is in simply acts
        self.assertEqual((view["hand"]["phase"], view["hand"]["target_is_hero"]), ("flop", True))

    def test_ops_14_all_in_or_fold_a_shove_in_front_of_hero_noticed_late(self):
        s = aof(stacks={4: 5})                                      # CO seat 4 (5bb), hero on the button
        s.do("act", kind="allin")                                   # hero shoves; the cutoff is passed by
        view = s.do("act", seat=4, kind="allin")                    # no: the cutoff had shoved first
        self.assertEqual([(e["seat"], e["allin"], e["auto"]) for e in state(s).log], [(4, True, False), (1, True, False)])
        self.assertIsNone(view["toast"])
        s.do("close_round")                                         # the blinds fold
        view = s.do("act", seat=3, kind="allin")                    # ... and the big blind had called after all
        self.assertIn("Added to the betting before the flop: BB calls all-in", toast_of(view))
        self.assertEqual(sorted(view["hand"]["pots"][0]["eligible"]), [1, 3, 4])

    def test_ops_14_a_player_sitting_out_keeps_his_defaults(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("set_status", seat=3, status="away")
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("close_round")
        err = refused(s, "act", seat=3, kind="call")
        self.assertIn("sitting out", err.message)
        self.assertIn("back", err.fix)


class T1ABetWhileCardsAreWanted(unittest.TestCase):
    """T1: while the hand waits for a street's cards, the round just closed opens again only for a call or a check.

    A bet, a raise or an all-in typed for a seat then is refused with what to do: the cards first.
    """

    def flop_wanted(self, stacks=None):
        """6 seats, 100/200 ante 25, button on hero.  CO raises to 500, hero calls, Enter: the blinds fold."""
        s = tournament(size=6, level="100/200/25", stacks=stacks or [20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        view = s.do("close_round")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("flop", "board"))
        return s

    def test_t1_a_bet_a_raise_and_an_all_in_are_refused_with_the_cards_to_type(self):
        s = self.flop_wanted()
        for kind, amount, word in (("bet", 600, "bet"), ("raise", 2000, "raise"), ("allin", None, "all-in"),
                                   ("bet", None, "bet"), ("raise", None, "raise")):
            for seat in (2, 3, 4, 5):                               # the blinds, and two players passed by in front
                err = refused(s, "act", seat=seat, kind=kind, amount=amount)
                self.assertEqual(err.message, f"Type the flop first (K S 7 D 2 C), then record the {word}.", (kind, seat))
                self.assertEqual(err.fix, "A bet or raise he made before the flop: select his fold on the hand line, "
                                          "then Raised.", (kind, seat))
        self.assertEqual(state(s).phase, "flop")
        self.assertFalse([e for e in state(s).log if e["kind"] in ("bet", "raise") and e["seat"] != 6])

    def test_t1_the_forgotten_caller_still_fits_and_then_the_bet_goes_on_the_flop(self):
        s = self.flop_wanted()
        view = s.do("act", seat=3, kind="call")                     # reopening is for a call
        self.assertEqual(toast_of(view), "Added to the betting before the flop: BB calls")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("flop", "board"))
        s.do("set_cards", board="Ks7d2c")                           # as the refusal says: the flop first ...
        view = s.do("act", seat=3, kind="bet", amount=600)          # ... then the bet
        self.assertEqual((marked(s)[-2:], view["hand"]["to_call"]), (["Ks 7d 2c", "BB bet 3bb"], 600))
        # the same for the player who was never mentioned: the flop, then his bet (he must have called)
        s = self.flop_wanted()
        refused(s, "act", seat=3, kind="bet", amount=600)
        s.do("set_cards", board="Ks7d2c")
        view = s.do("act", seat=3, kind="bet", amount=600)
        self.assertIn("now he called there, and bets 600 here", toast_of(view))
        self.assertEqual([(e["street"], e["kind"]) for e in state(s).log if e["seat"] == 3],
                         [("preflop", "call"), ("flop", "bet")])

    def test_t1_the_turn_and_the_river_are_named_and_an_implied_check_says_undo(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        s.do("close_round")                                         # the flop is checked through, says Enter
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("turn", "board"))
        err = refused(s, "act", seat=6, kind="bet", amount=700)     # the cutoff's check on the flop was implied
        self.assertEqual((err.message, err.fix), ("Type the turn first (5 H), then record the bet.",
                                                  "A bet or raise he made on the flop: undo to that point (Backspace)."))
        err = refused(s, "act", seat=2, kind="allin")               # folded before the flop on the record
        self.assertEqual(err.message, "Type the turn first (5 H), then record the all-in.")
        self.assertIn("on the flop: undo to that point", err.fix)
        s.do("set_cards", board="Ks7d2c5h")
        s.do("close_round")
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("river", "board"))
        err = refused(s, "act", seat=3, kind="raise")
        self.assertEqual(err.message, "Type the river first (9 C), then record the raise.")
        view = s.do("act", seat=3, kind="check")                    # a check is taken: the players behind him decide again
        self.assertEqual((view["hand"]["phase"], state(s).log[-1]["street"]), ("turn", "turn"))

    def test_t1_a_player_whose_last_action_was_typed_acts_on_the_new_street_as_before(self):
        s = self.flop_wanted()
        view = s.do("act", seat=6, kind="bet", amount=700)          # the raiser: nothing of his was implied
        self.assertEqual((state(s).log[-1]["street"], state(s).log[-1]["kind"], view["hand"]["to_call"]), ("flop", "bet", 700))
        self.assertEqual([e["kind"] for e in state(s).log if e["street"] == "preflop" and not e["auto"]], ["raise", "call"])

    def test_t1_an_all_in_that_can_only_be_a_call_is_the_forgotten_caller(self):
        s = self.flop_wanted(stacks=[20000, 20000, 450, 20000, 20000, 20000])     # the big blind has 425 after the ante
        view = s.do("act", seat=3, kind="allin")
        self.assertEqual(toast_of(view), "Added to the betting before the flop: BB calls all-in")
        self.assertEqual([(e["kind"], e["allin"]) for e in state(s).log if e["seat"] == 3], [("call", True)])

    def test_t1_your_own_seat_and_no_seat(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "4 call")
        s.do("close_round")                                         # hero and the blinds take the default
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("flop", "board"))
        err = refused(s, "act", seat=1, kind="raise", amount=900)   # hero is folded on the record
        self.assertEqual((err.message, err.fix), ("Type the flop first (K S 7 D 2 C), then record the raise.",
                                                  "A bet or raise you made before the flop: select your fold on the "
                                                  "hand line, then Raised."))
        view = s.do("act", kind="bet", amount=300)                  # no seat named: the next player, on the flop
        self.assertEqual((view["hand"]["phase"], state(s).log[-1]["street"]), ("flop", "flop"))


def played_again(text: str) -> Session:
    """Play a hand again from nothing but its text in the hand history (Y, Copy as text) -> the new session.

    Reads the blinds, the seats line and every action as a person would, and types them into a fresh table.
    """
    import itertools
    import re

    def number(words):
        return float(words.replace(",", "").replace("bb", ""))

    lines = text.split("\n")
    head = re.match(r"Hand \d+ \| ([\d,.]+)/([\d,.]+)(?: (bb )?ante ([\d,.]+))? \| (\d+) players(?: \| fee [\d.]+bb)?"
                    r"(?: \| dead button on seat (\d+))?(?: \| you (\S+) (\S+) \()?", lines[0])
    assert head, lines[0]
    sb, bb, bb_ante, ante, players, dead_button, hero_pos, hero_cards = head.groups()
    assert lines[1].startswith("Seats: "), lines[1]
    seats = {}
    for part in lines[1][len("Seats: "):].split("; "):
        m = re.match(r"(\d+) (\S+) ([\d,.]+)(bb)?(?: (.*?))??( \(sitting out\))?$", part)
        assert m, part
        seats[int(m.group(1))] = {"pos": m.group(2), "stack": m.group(3).replace(",", ""), "name": m.group(5) or "",
                                  "away": bool(m.group(6)), "bb": bool(m.group(4))}
    assert len(seats) == int(players)
    aof_mode = any(seat["bb"] for seat in seats.values())
    s = Session(save=False)
    if aof_mode:
        s.do("set_mode", mode="aof")
        s.do("new_session")
    else:
        s.do("new_session", size=max(2, max(seats), int(dead_button or 0)), start_stack=10000)
        if bb_ante:
            s.do("set_ante_kind", kind="bb")
            s.do("set_level", text=f"{sb}/{bb}/{ante}".replace(",", ""))
        else:
            s.do("set_level", text=f"{sb}/{bb}/{ante or 0}".replace(",", ""))
    for number_ in range(2, s.view()["table"]["size"] + 1):
        if number_ not in seats:
            s.do("clear_seat", seat=number_)
    for number_, seat in seats.items():
        s.do("set_stack", seat=number_, text=seat["stack"])
        if number_ != HERO:
            s.do("rename", seat=number_, name=seat["name"])
        if seat["away"]:
            s.do("set_status", seat=number_, status="away")
    button = int(dead_button) if dead_button else next(n for n, seat in seats.items() if seat["pos"].startswith("BTN"))
    s.do("set_button", seat=button)
    view = s.do("deal", hero_cards=hero_cards if hero_cards and hero_cards != "??" else None)
    assert {str(n): seat["pos"] for n, seat in seats.items()} == view["hand"]["positions"], (seats, view["hand"]["positions"])
    who = {(seat["name"] or seat["pos"]): n for n, seat in seats.items()}
    who.update({"You": HERO} if HERO in seats else {})
    result = ""
    for row in lines[2:]:
        title, _, said = row.partition(": ")
        if title == "Result":
            result = said
        street = title.split(" ")[0].lower()
        if street not in BETTING:
            continue
        cards = "".join(title.split(" ")[1:])
        if cards:
            s.do("set_cards", slot=street, text=cards)
        for step in ([] if said == "no action recorded" else said.split(", ")):
            name = max((n for n in who if step.startswith(n + " ")), key=len)
            verb = step[len(name) + 1:]
            kind = verb.split(" ")[0]
            amount = None
            if kind in ("bet", "raise", "all-in") and "(" in verb:        # "raise to 1,320 (2.2bb)": the chips are exact
                amount = int(number(verb.replace("raise to", "raise").split(" ")[1]))
            s.do("act", seat=who[name], kind={"all-in": "allin"}.get(kind, kind), amount=None if kind == "all-in" else amount)
        now = s.view()["hand"]
        if now["phase"] == street and now["needs"] == "action" and "not recorded" not in text:
            s.do("close_round")                         # whoever is not mentioned folded (or checked) when his turn came
    if s.view()["hand"]["needs"] == "result" and result and "you folded" not in result and result != "not recorded":
        winners = [HERO if w.startswith(("You", "you")) else int(re.match(r"[Ss]eat (\d+)", w).group(1)) for w in result.split(", ")]
        tiers = [[list(order[:k]), *[[x] for x in order[k:]]] for order in itertools.permutations(winners)
                 for k in range(1, len(winners) + 1)] + [[[x] for x in order] for order in itertools.permutations(winners)]
        for ranking in tiers:                           # the result names who won what: find the order of the hands
            trial = copy.deepcopy(s.data)
            try:
                view = s.do("award", ranking=ranking)
            except ModelError:
                s.data = trial
                continue
            if view["hand"]["result"]["text"] == result:
                break
            s.do("undo")
    return s


class TheHistoryTextIsEnoughToPlayTheHandAgain(unittest.TestCase):
    """The text of a finished hand (Y, Copy as text) carries every seat, position and stack and every bet in chips.

    It used to say "8 players" and round every amount to a tenth of a big blind, so the hand could not
    be put on a table again from it.
    """

    def again(self, s):
        """The newest hand of ``s`` played again from its text: the same text comes out, and the same stacks."""
        entry = s.view()["history"][0]
        replayed = played_again(entry["text"])
        self.assertEqual(replayed.view()["history"][0]["text"].split("\n", 1)[1], entry["text"].split("\n", 1)[1])
        first, second = s.view()["hand"], replayed.view()["hand"]
        if first["result"]:
            self.assertEqual(second["result"]["net"], first["result"]["net"])
        return entry["text"]

    def test_the_text_names_every_seat_stack_and_bet_in_chips(self):
        s = tournament(size=6, level="300/600/75", stacks=[12900, 20000, 5425, 20000, 20000, 20000])
        s.do("rename", seat=2, name="Bob")
        s.do("set_status", seat=5, status="away")
        s.do("deal", hero_cards="AhKh")
        play(s, "4 raise 1320, 1 allin, 3 allin, 4 call")
        s.do("set_cards", board="Ks7d2c5h9c")
        s.do("award", ranking=[[3], [1]])
        text = self.again(s)
        self.assertEqual(text.split("\n")[:3], [
            "Hand 1 | 300/600 ante 75 | 6 players | you BTN AhKh (21.5bb)",
            "Seats: 1 BTN 12,900 You; 2 SB 20,000 Bob; 3 BB 5,425; 4 LJ 20,000; 5 HJ 20,000 (sitting out); 6 CO 20,000",
            "Preflop: LJ raise to 1,320 (2.2bb), You all-in 12,825 (21.4bb), BB call all-in, LJ call"])
        self.assertIn("Result: You (BTN) win 14,950, seat 3 (BB) wins 16,800", text)
        # what you did beside the coach's word is written as on the hand line: "all-in", not the program's "allin"
        s = tournament(size=6, level="300/600/75", stacks=[12900, 20000, 40000, 20000, 20000, 20000])
        s.do("deal", hero_cards="AhAd")
        s.record_advice(s.rev, "RAISE", {"kind": "raise", "to": 1200})
        play(s, "1 allin")
        text = s.do("close_round")["history"][0]["text"]
        self.assertIn("Coach (preflop): RAISE | you: all-in | deviated", text)

    def test_hands_of_every_kind_come_out_the_same_when_played_again(self):
        # folded round to the big blind; a raise that takes the blinds
        s = tournament(size=8, level="300/600/75", stacks=[12900, 23400, 18500, 12500, 20000, 20000, 20000, 20000], button=4)
        s.do("deal", hero_cards="72o")
        play(s, "1 fold")
        s.do("close_round")
        self.again(s)
        s.do("deal", hero_cards="QQ")
        s.do("act", seat=1, kind="raise", amount=3900)
        s.do("close_round")
        self.assertIn("You raise to 3,900 (6.5bb)", self.again(s))
        # three streets with bets that are no round number of big blinds, a named player, and a split pot
        s = tournament(size=6, level="100/200/25", stacks=[20000, 19350, 18775, 20000, 20000, 20000])
        s.do("rename", seat=3, name="Big Ann")
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 525, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        play(s, "3 check, 6 bet 1175, 1 raise 3325, 3 fold, 6 call")
        s.do("set_cards", slot="turn", text="5h")
        play(s, "6 check, 1 check")
        s.do("set_cards", slot="river", text="9c")
        play(s, "6 bet 4150, 1 call")
        s.do("award", ranking=[[1, 6]])
        text = self.again(s)
        self.assertIn("Flop Ks 7d 2c: Big Ann check, CO bet 1,175 (5.9bb), You raise to 3,325 (16.6bb), Big Ann fold, CO call", text)
        # a big-blind ante, a player all-in for less than the big blind, three players at the showdown
        s = tournament(size=4, level="500/1000", stacks=[20000, 700, 20000, 9000])
        s.do("set_ante_kind", kind="bb")
        s.do("set_level", text="500/1000/1000")
        s.do("deal", hero_cards="AhAd")
        play(s, "4 allin, 1 call, 2 allin, 3 fold")
        s.do("award", ranking=[[2], [4], [1]])
        self.assertIn("bb ante 1,000", self.again(s))
        # a dead button: the small blind of the hand before went out
        s = tournament(size=4, level="100/200/25", stacks=[5000, 300, 5000, 5000])
        s.do("deal", hero_cards="72o")
        play(s, "4 fold, 1 fold, 2 allin, 3 call")
        s.do("award", winner=3)                                     # seat 2 is out: the button rests on his seat
        s.do("deal", hero_cards="AKs")
        self.assertEqual(s.view()["hand"]["button"], 2)
        play(s, "1 raise 500")
        s.do("close_round")
        self.assertIn("dead button on seat 2", self.again(s))
        # All-In or Fold counts in big blinds, and takes its fee
        s = aof({2: "5.5", 3: "5.5", 4: "5.5"})
        play(s, "4 fold, 1 allin, 2 allin, 3 fold")
        s.do("award", winner=2)
        text = self.again(s)
        self.assertIn("Seats: 1 BTN 8bb You; 2 SB 5.5bb; 3 BB 5.5bb; 4 CO 5.5bb", text)
        self.assertIn("\nYou: -5.5bb", text)                        # in big blinds, like the result above it


class DeletingYourOwnActionSaysWhatItDoes(unittest.TestCase):
    """Delete on your own call, with a caller behind you on the record, left you folded without a word."""

    def test_deleting_heros_action_that_players_behind_him_followed_is_said(self):
        s = tournament(size=8, level="300/600/75", stacks=[20000] * 8)
        s.do("deal", hero_cards="AhKh")
        play(s, "5 raise 1320, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        mine = next(item["i"] for item in s.view()["hand"]["line"] if item["text"] == "You call")
        view = s.do("remove_event", index=mine)
        self.assertIn("You fold*", marked(s))                       # the big blind's call stands: you were passed by
        self.assertEqual(toast_of(view), "Without that action you are folded on the record. Backspace brings it back")
        self.assertEqual(marked(s.do("undo") and s), [x for x in marked(s)])
        self.assertIn("You call", marked(s))                        # one undo and the call is back
        # deleting the last action of the hand so far leaves you to act again: nothing to say
        s = tournament(size=8, level="300/600/75", stacks=[20000] * 8)
        s.do("deal", hero_cards="AhKh")
        play(s, "5 raise 1320, 1 call")
        mine = next(item["i"] for item in s.view()["hand"]["line"] if item["text"] == "You call")
        view = s.do("remove_event", index=mine)
        self.assertEqual((toast_of(view), view["hand"]["target_is_hero"]), ("", True))
        # an opponent's action deleted: nothing about you
        play(s, "1 call, 3 call")
        theirs = next(item["i"] for item in s.view()["hand"]["line"] if item["text"] == "BB call")
        self.assertNotIn("you are folded", toast_of(s.do("remove_event", index=theirs)))


class NoButtonToCheckOnceAGameIsOver(unittest.TestCase):
    """A Spin game ended and the toast still said "Button on seat 1: check it against your table".

    With one player left no hand can be dealt: there is no button to check.
    """

    def test_a_finished_spin_game_says_how_it_ended_and_nothing_about_the_button(self):
        s = spin()                                                  # hero on the button, 300 chips each
        play(s, "1 allin, 2 allin, 3 allin")
        view = s.do("award", winner=1)                              # you take every chip
        self.assertEqual(toast_of(view), "You won this game. Press N for a new one.")
        s = spin()
        play(s, "1 allin, 2 allin, 3 allin")
        view = s.do("award", winner=2)                              # seat 2 does
        self.assertEqual(toast_of(view), "You lost this game. Press N for a new one.")
        # with two players left there is a next hand: after a blind went out the toast still asks to check the button
        s = spin()
        play(s, "1 fold, 2 allin, 3 allin")
        view = s.do("award", winner=2)                              # the big blind is out: heads-up
        self.assertIn("check it against your table", toast_of(view))


class D9AnAllInForMoreThanAnybodyCanMatch(unittest.TestCase):
    """D9: hero covers everybody.  The coach names what can be matched (5.5bb), the All-in button the stack (8bb).

    The view carries both (``hand.legal.allin`` and ``hand.allin_matched``) so the page can say both, and
    an all-in recorded from the coach's button is the whole stack: the part nobody matched comes back.
    """

    def test_d9_the_view_says_the_stack_and_what_can_be_matched(self):
        s = aof({2: "5.5", 3: "5.5", 4: "5.5"})                     # hero has the full 8bb, on the button
        s.do("act", seat=4, kind="fold")
        hand = s.view()["hand"]
        self.assertEqual((hand["target"], hand["legal"]["allin"], hand["allin_matched"]), (1, 8, 5.5))
        # the coach's button sends {"kind": "allin"} (and may send what can be matched as "to"): the whole stack goes in
        view = s.do("act", seat=1, kind="allin", to=5.5, via="follow")
        self.assertEqual((view["hand"]["line"][-1]["text"], stack(s, 1), state(s).in_front[1]), ("You all-in 8bb", 0, 8))
        view = play(s, "2 allin, 3 fold")                           # one caller for his 5.5bb
        self.assertEqual((view["hand"]["needs"], state(s).returned), ("result", {1: 2.5}))
        self.assertEqual((stack(s, 1), [(p["amount"], p["eligible"]) for p in view["hand"]["pots"]]), (2.5, [(12, [1, 2])]))

    def test_d9_matched_is_the_all_in_itself_when_somebody_covers_it(self):
        s = tournament(size=3, level="500/1000/0", stacks=[8000, 5500, 5500])
        hand = s.do("deal", hero_cards="AhAd")["hand"]
        self.assertEqual((hand["legal"]["allin"], hand["allin_matched"]), (8000, 5500))
        s = tournament(size=3, level="500/1000/0", stacks=[8000, 5500, 20000])
        hand = s.do("deal", hero_cards="AhAd")["hand"]
        self.assertEqual((hand["legal"]["allin"], hand["allin_matched"]), (8000, 8000))
        hand = play(s, "1 fold")["hand"]                            # an opponent's all-in, as it is recorded for him:
        self.assertEqual((hand["target"], hand["legal"]["allin"], hand["allin_matched"]), (2, 5500, 5500))     # the big blind covers him
        # players who folded do not count: only the big blind is left, with 3,000 in all
        s = tournament(size=3, level="500/1000/0", stacks=[8000, 20000, 3000])
        s.do("deal", hero_cards="AhAd")
        play(s, "1 raise 2000, 2 fold, 3 call")
        hand = s.do("set_cards", board="Ks7d2c")["hand"]            # on the flop you have 6,000 behind, he has 1,000
        self.assertEqual((hand["target"], hand["legal"]["allin"], hand["allin_matched"]), (1, 6000, 1000))
        s.do("act", seat=1, kind="fold")                            # the hand is over: nobody is to act, nothing to say
        self.assertIsNone(s.view()["hand"]["allin_matched"])


class D6AFoldForAnImpliedCheckWhileCardsAreWanted(unittest.TestCase):
    """D6: a fold typed for a seat whose check in the round just closed was only implied, while the next
    street's cards are wanted, is refused like a bet typed then: the cards first.  It used to be taken
    into the closed round, which opened again for the players behind him.
    """

    def turn_wanted(self):
        """6 seats, button on hero.  CO raises, hero and the big blind call; the flop is checked through by Enter."""
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        view = s.do("close_round")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("turn", "board"))
        return s

    def test_d6_a_fold_for_an_implied_check_is_refused_with_the_cards_to_type(self):
        s = self.turn_wanted()
        before = (marked(s), s.rev)
        for seat in (3, 6, 1):                                      # the big blind, the cutoff, and your own seat
            err = refused(s, "act", seat=seat, kind="fold")
            self.assertEqual(err.message, "Type the turn first (5 H), then record the fold.", seat)
            he = "you" if seat == 1 else "he"
            self.assertEqual(err.fix, f"On the record {he} checked on the flop, where a check was free: "
                                      "a fold now is on the turn.", seat)
        self.assertEqual((marked(s), s.rev), before)                # nothing changed: the flop round did not open again
        self.assertEqual((s.view()["hand"]["phase"], s.view()["hand"]["needs"]), ("turn", "board"))
        self.assertFalse([e for e in state(s).log if e["kind"] == "fold" and e["seat"] in (1, 3, 6)])

    def test_d6_the_cards_first_and_then_the_fold_is_on_the_new_street(self):
        s = self.turn_wanted()
        refused(s, "act", seat=3, kind="fold")
        s.do("set_cards", board="Ks7d2c5h")                         # as the refusal says
        s.do("act", seat=3, kind="fold")
        self.assertEqual([(e["street"], e["kind"]) for e in state(s).log if e["seat"] == 3][-2:],
                         [("flop", "check"), ("turn", "fold")])
        # the river wanted: the same sentence with the river's card
        s = self.turn_wanted()
        s.do("set_cards", board="Ks7d2c5h")
        s.do("close_round")
        err = refused(s, "act", seat=6, kind="fold")
        self.assertEqual((err.message, err.fix), ("Type the river first (9 C), then record the fold.",
                                                  "On the record he checked on the turn, where a check was free: "
                                                  "a fold now is on the river."))

    def test_d6_what_stays_as_it_was(self):
        # before the flop the big blind's free check was implied by Enter: the fold waits for the flop too
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "1 call")
        s.do("close_round")                                         # the small blind folds, the big blind checks
        self.assertEqual(s.view()["hand"]["needs"], "board")
        err = refused(s, "act", seat=3, kind="fold")
        self.assertEqual(err.message, "Type the flop first (K S 7 D 2 C), then record the fold.")
        # a check or a call for him is still taken into the closed round (the forgotten caller's rule)
        view = s.do("act", seat=3, kind="check")
        self.assertEqual(toast_of(view), "Added to the betting before the flop: BB checks")
        # at the showdown nothing waits for cards: a fold for an implied check on the river is his fold there
        s = self.turn_wanted()
        s.do("set_cards", board="Ks7d2c5h9c")                       # (typing the river checks the turn through)
        s.do("close_round")                                         # ... and Enter the river
        self.assertEqual(s.view()["hand"]["needs"], "result")
        view = s.do("act", seat=3, kind="fold")
        self.assertEqual(toast_of(view), "Added to the betting on the river: BB folds")
        # a player whose check was typed acts on the new street, as before
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        play(s, "3 check, 6 check, 1 check")
        self.assertEqual(s.view()["hand"]["needs"], "board")
        s.do("act", seat=3, kind="fold")
        self.assertEqual(state(s).log[-1]["street"], "turn")


class T2AFoldForAPlayerAlreadyFolded(unittest.TestCase):
    """T2: a fold typed for a player the record has out since an earlier street changes nothing and says so."""

    def test_t2_a_fold_on_the_flop_for_a_player_folded_before_it(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")                           # the blinds get the implied fold
        line, pot = marked(s), s.view()["hand"]["pot"]
        for seat, name in ((3, "BB"), (2, "SB"), (4, "LJ")):
            err = refused(s, "act", seat=seat, kind="fold")
            self.assertEqual((err.message, err.fix), (f"{name} is already folded on the record.", ""))
        self.assertEqual((marked(s), s.view()["hand"]["pot"]), (line, pot))        # nobody was put back in with a call
        self.assertNotIn("BB call~", marked(s))
        s.do("rename", seat=3, name="Carl")
        self.assertEqual(refused(s, "act", seat=3, kind="fold").message, "Carl is already folded on the record.")

    def test_t2_a_fold_while_the_cards_are_wanted_does_not_reopen_the_round(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("close_round")                                         # Enter: the blinds fold, the flop is wanted
        err = refused(s, "act", seat=2, kind="fold")
        self.assertEqual(err.message, "SB is already folded on the record.")
        view = s.view()
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("flop", "board"))
        self.assertEqual(marked(s)[-2:], ["SB fold*", "BB fold*"])

    def test_t2_at_the_showdown_and_for_hero(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 3 call")                              # hero on the button is passed by: an implied fold
        s.do("set_cards", board="Ks7d2c")
        self.assertEqual(refused(s, "act", seat=1, kind="fold").message, "You are already folded on the record.")
        s.do("set_cards", board="Ks7d2c5h9c")
        s.do("close_round")
        self.assertEqual(s.view()["hand"]["needs"], "result")
        self.assertEqual(refused(s, "act", seat=2, kind="fold").message, "SB is already folded on the record.")

    def test_t2_the_other_actions_still_say_he_must_have_called(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call")
        s.do("set_cards", board="Ks7d2c")
        self.assertIn("now he called there, and checks here", toast_of(s.do("act", seat=3, kind="check")))
        # and a fold on the street being played still takes the place of the one nobody typed
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 4 fold")
        self.assertEqual(marked(s)[1:4], ["LJ fold", "HJ fold*", "CO raise 2.5bb"])


class T3TheBigBlindFirst(unittest.TestCase):
    """T3: an action typed for the big blind before anybody has come in gets a sentence that says what to do."""

    MESSAGE = "Nobody has entered the pot before the big blind."
    FIX = "Record who called or raised first, or press Enter if everybody folded."

    def test_t3_the_first_typed_action_is_for_the_big_blind(self):
        for kind in ("check", "call", "fold", "raise", "allin"):
            s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
            s.do("deal", hero_cards="AhKh")
            err = refused(s, "act", seat=3, kind=kind)
            self.assertEqual((err.message, err.fix), (self.MESSAGE, self.FIX), kind)
            self.assertNotIn("no turn", err.message)
        view = s.do("act", seat=5, kind="call")                     # as it says: who came in first ...
        view = s.do("act", seat=3, kind="check")                    # ... then the big blind has his option
        self.assertEqual((view["hand"]["phase"], marked(s)[-1]), ("flop", "BB check"))

    def test_t3_after_typed_folds_in_front_and_with_hero_in_the_big_blind(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6, button=5)   # hero is the big blind
        s.do("deal", hero_cards="AhKh")
        self.assertEqual(s.view()["table"]["seats"][0]["pos"], "BB")
        play(s, "2 fold, 3 fold")
        err = refused(s, "act", seat=1, kind="check")
        self.assertEqual((err.message, err.fix), (self.MESSAGE, self.FIX))
        view = s.do("close_round")                                  # Enter: everybody folded, the blind comes back
        self.assertEqual((view["hand"]["needs"], view["hand"]["result"]["winners"][0]["seat"]), ("next", 1))

    def test_t3_heads_up_and_all_in_or_fold(self):
        s = tournament(size=2, level="100/200/25", stacks=[20000] * 2, button=1)   # hero is the button and small blind
        s.do("deal", hero_cards="AhKh")
        self.assertEqual(refused(s, "act", seat=2, kind="check").message, self.MESSAGE)
        s = aof()                                                   # hero on the button, the big blind is seat 3
        err = refused(s, "act", seat=3, kind="allin")
        self.assertEqual((err.message, err.fix), (self.MESSAGE, "Record who moved all-in first, or press Enter if everybody folded."))

    def test_t3_no_turn_now_is_still_the_answer_where_it_is_true(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 1 call, 2 call, 3 call")
        s.do("set_cards", board="Ks7d2c")
        play(s, "2 check, 3 check, 6 check, 1 check")               # the flop is over, the turn card is typed
        s.do("set_cards", board="Ks7d2c5h")
        play(s, "2 bet 400, 3 call, 6 call, 1 call")
        s.do("set_cards", board="Ks7d2c5h9c")
        play(s, "2 check, 3 check, 6 check")
        self.assertIn("no turn now", refused(s, "act", seat=2, kind="bet", amount=500).message)


class T4TheWinnerBySeatAndPosition(unittest.TestCase):
    """T4: the result names the winner by seat number and that hand's position, in the coach's own words."""

    def test_t4_the_result_text_on_screen_and_in_the_history(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("rename", seat=3, name="Carl")                         # a name does not change the line
        s.do("deal", hero_cards="AhKh")
        play(s, "6 raise 500, 3 call")
        s.do("set_cards", board="Ks7d2c5h9c")
        s.do("close_round")
        view = s.do("award", winner=3)
        self.assertEqual(view["hand"]["result"]["text"], "Seat 3 (BB) wins 1,250")
        self.assertIn("Result: Seat 3 (BB) wins 1,250", view["history"][0]["text"])
        self.assertEqual(view["table"]["seats"][2]["pos"], "SB")    # the table is the next hand's: he is the small blind now
        self.assertEqual(view["hand"]["positions"]["3"], "BB")      # ... and the line names the seat of the hand played

    def test_t4_hero_a_split_and_big_blinds(self):
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "1 raise 500, 3 call")
        s.do("set_cards", board="Ks7d2c5h9c")
        s.do("close_round")
        view = s.do("award", winners=[1, 3])
        self.assertEqual(view["hand"]["result"]["text"], "You (BTN) win 625, seat 3 (BB) wins 625")
        self.assertIn("Result: You (BTN) win 625, seat 3 (BB) wins 625", view["history"][0]["text"])
        s = aof()                                                   # hero on the button
        s.do("act", kind="allin")
        view = s.do("close_round")                                  # everybody folds: the pot less the fee
        self.assertEqual(view["hand"]["result"]["text"], "You (BTN) win 2.4bb")

    def test_t4_the_same_words_as_the_coach(self):
        from poker_coach.app import advice as A
        s = tournament(size=6, level="100/200/25", stacks=[20000] * 6)
        s.do("deal", hero_cards="AhKh")
        play(s, "1 raise 500, 3 call")
        s.do("set_cards", board="Ks7d2c5h9c")
        s.do("close_round")
        for award in ({"winner": 3}, {"winners": [1, 3]}, {"winner": 1}):
            view = s.do("award", **award)
            self.assertTrue(A.advise(s)["spot"].startswith(view["hand"]["result"]["text"] + ". "), award)
            s.do("undo")


class T8TheKeysSheet(unittest.TestCase):
    """T8: the sentences of the keys sheet say what the keys do now (the page reads them from defaults.py)."""

    def text_of(self, group, command):
        rows = [row for row in Session(save=False).view()["settings"]["keys"][group] if row["do"] == command]
        self.assertEqual(len(rows), 1, command)
        return rows[0]["text"]

    def test_t8_the_key_sentences(self):
        for command in ("bet", "raise"):
            text = self.text_of("table", command)
            self.assertIn("Your own: type the amount, then Enter", text)
            self.assertIn("An opponent's is recorded at the usual size; E changes it", text)
        enter = self.text_of("table", "accept")
        for part in ("The rest fold (or check)", "While you record the players in front of you in turn: they fold and "
                     "the keys are yours", "While a street's cards are wanted: skip the board",
                     "While a split is ticked: split"):
            self.assertIn(part, enter)
        self.assertIn("Three or more players: tick who shares it with the seat numbers, then Enter",
                      self.text_of("table", "split"))
        self.assertIn("In a field: the old value comes back", self.text_of("table", "cancel"))
        self.assertIn("an empty seat too", self.text_of("seat", "button"))

    def test_t8_the_words_of_the_page_are_the_words_of_the_sheet(self):
        """The page says Button forward and shows the hand as steps (the second page agent's two word items)."""
        self.assertEqual((self.text_of("table", "line_back"), self.text_of("table", "line_on")),
                         ("Previous step of the hand", "Next step of the hand"))
        self.assertEqual((self.text_of("table", "button_back"), self.text_of("table", "button_on")),
                         ("Dealer button one seat back", "Dealer button one seat forward"))

    def test_t8_the_keys_named_in_the_sentences_are_the_keys_of_the_map(self):
        keys = {row[1]: row[0] for row in D.KEYS_TABLE}
        self.assertEqual((keys["edit"][0], keys["accept"][0], keys["split"][0], keys["cancel"][0]),
                         ("e", "Enter", "Shift+W", "Escape"))
        for group in D.KEYS.values():
            for _, command, text in group:
                self.assertFalse(text.endswith("."), command)       # one style: no full stop at the end of a row
                self.assertLess(len(text), 200, command)


class SeenInPassing(unittest.TestCase):
    """Small things the reviewers met on the way (the addendum's last list)."""

    def test_icm_is_exact_only_with_a_prize_for_every_paid_place(self):
        s = tournament(size=6, entrants=500, remaining=96, paid=75)
        self.assertEqual((s.view()["strip"]["icm"], s.view()["strip"]["prizes_typed"]), ("on", 0))
        strip = s.do("set_tournament", payouts="1:1000 2:600 3:400")["strip"]      # three prizes for 75 places
        self.assertEqual((strip["icm"], strip["prizes_typed"], strip["paid"]), ("on", 3, 75))
        strip = s.do("set_tournament", payouts="1:1000 2:600 3:400 4-75:20")["strip"]
        self.assertEqual((strip["icm"], strip["prizes_typed"]), ("exact", 75))
        strip = s.do("set_tournament", paid="")["strip"]            # no number of paid places: the list is the ladder
        self.assertEqual(strip["icm"], "exact")
        self.assertEqual(s.do("set_tournament", payouts="auto")["strip"]["prizes_typed"], 0)

    def test_the_whole_text_is_named_when_an_amount_cannot_be_read(self):
        s = tournament(size=6)
        s.do("deal")
        self.assertIn("'banana'", refused(s, "act", seat=4, kind="raise", amount="banana").message)
        self.assertIn("'banana'", refused(s, "set_stack", seat=2, text="banana").message)

    def test_a_hand_left_after_heros_fold_is_you_folded(self):
        s = tournament(size=6, level="100/200/25")
        s.do("deal", hero_cards="72o")
        s.do("act", kind="fold")                                    # hero folds on the button
        view = s.do("deal")                                         # N: the next hand
        entry = view["history"][0]
        self.assertEqual((entry["no"], entry["skipped"], entry["did"], entry["net"]), (1, False, "fold", -25))
        self.assertIn("Result: you folded (-25); who won the pot was not recorded", entry["text"])
        self.assertNotIn("Result: not recorded", entry["text"])
        s.do("set_cards", hero="AKs")
        s.do("act", seat=5, kind="raise", amount=500)
        view = s.do("skip_hand", hero_in=True)                      # hero was still in: that one is not recorded
        self.assertEqual((view["history"][0]["skipped"], view["history"][0]["net"]), (True, None))


if __name__ == "__main__":
    unittest.main()
