"""Tests for the poker coach engine.  Run: python -m unittest discover -s tests"""

import copy
import io
import json
import os
import random
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from poker_coach import state as S
from poker_coach.cards import (HAND_INDEX, HANDS, class_of, format_range, parse_cards, parse_hand,
                               parse_range, range_pct)
from poker_coach.cli import main
from poker_coach.equity import allin_order, class_equity, eq_vs_range, hand_equity, matrix
from poker_coach.evaluator import category, describe, evaluate
from poker_coach.icm import Prizes, default_payouts, hero_equity, mh_exact
from poker_coach.postflop import PostflopSpot, Villain, advise_postflop, parse_line, range_from_spec
from poker_coach.preflop import advise, quick_spot
from poker_coach.pushfold import HandSetup, nash_push_range, solve_open_shove
from poker_coach.ranges import rfi_range


def ev(s):
    return evaluate(parse_cards(s))


class Evaluator(unittest.TestCase):
    def test_categories(self):
        cases = {
            "AsKsQsJsTs2c3d": "straight flush", "5s4s3s2sAs8d7d": "straight flush",
            "AsAdAhAc2s3d4h": "four of a kind", "AsAdAhKcKs3d4h": "full house",
            "As2s9s7s4s3dKh": "flush", "As2d3h4c5s9dKh": "straight",
            "AsAdAh4c5s9dKh": "three of a kind", "AsAd4h4c5s9dKh": "two pair",
            "AsAd3h4c6s9dKh": "pair", "As2d3h4c6s9dKh": "high card",
        }
        for cards, want in cases.items():
            self.assertEqual(category(ev(cards)), want, cards)

    def test_ordering(self):
        self.assertGreater(ev("AsAd4h4c5s9dKh"), ev("KsKd4h4c5s9dAh"))
        self.assertGreater(ev("AsKd2h3c5s9dTh"), ev("AsQd2h3c5s9dTh"))
        self.assertLess(ev("2s2d2h3c3s9dTh"), ev("3s3d3h2c2s9dTh"))
        self.assertLess(ev("As2d3h4c5s9dKh"), ev("6s2d3h4c5s9dKh"))  # wheel < six-high straight
        self.assertEqual(ev("AsKd2h3c5s9dTh"), ev("AhKc2h3c5s9dTh"))
        # two trips make a full house, three pairs keep the best two plus kicker
        self.assertEqual(category(ev("AsAdAhKcKsKd4h")), "full house")
        self.assertGreater(ev("AsAdKhKc4s4dQh"), ev("AsAdKhKc4s4dJh"))

    def test_five_and_six_cards(self):
        self.assertEqual(category(ev("AsKsQsJsTs")), "straight flush")
        self.assertEqual(category(ev("AsAd3h4c6s9d")), "pair")

    def test_describe(self):
        d = describe(parse_cards("AhKd"), parse_cards("Ks7d2c"))
        self.assertIn("top pair", d["made"])
        self.assertEqual(d["strength"], 5)
        d = describe(parse_cards("7h7d"), parse_cards("Ks7s2c"))
        self.assertIn("set", d["made"])
        d = describe(parse_cards("QhJh"), parse_cards("Th9h2c"))
        self.assertIn("flush_draw", d["flags"])
        self.assertIn("oesd", d["flags"])
        d = describe(parse_cards("AhKd"), parse_cards("Ks7d7c"))
        self.assertIn("paired board", d["made"])
        d = describe(parse_cards("2h3d"), parse_cards("AsAdKhKc9s"))
        self.assertEqual(d["strength"], 0)


class Cards(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(len(HANDS), 169)
        self.assertEqual(HANDS[class_of(*parse_cards("AhKh"))], "AKs")
        self.assertEqual(HANDS[class_of(*parse_cards("2c7d"))], "72o")
        self.assertEqual(HANDS[parse_hand("kas")[0]], "AKs")
        self.assertEqual(HANDS[parse_hand("10h 10d")[0]], "TT")
        self.assertEqual(parse_hand("AKo")[1], None)

    def test_ranges(self):
        r = parse_range("77+, ATs+, KTs+, QTs+, JTs, AJo+, KQo")
        self.assertAlmostEqual(range_pct(r), 136 / 1326 * 100, places=6)
        self.assertEqual(format_range(r), "77+, ATs+, KTs+, QTs+, JTs, AJo+, KQo")
        self.assertAlmostEqual(range_pct(parse_range("any")), 100.0)
        r = parse_range("A5s-A2s, T9s-76s, 22-55, KQ")
        for h in ("A4s", "87s", "44", "KQs", "KQo"):
            self.assertEqual(r[HAND_INDEX[h]], 1.0, h)
        self.assertEqual(r[HAND_INDEX["A6s"]], 0.0)
        top = parse_range("15%", list(allin_order()))
        self.assertAlmostEqual(range_pct(top), 15.0, places=4)
        self.assertEqual(parse_range("AJo:0.5")[HAND_INDEX["AJo"]], 0.5)
        with self.assertRaises(ValueError):
            parse_range("XYZ")


class Equity(unittest.TestCase):
    def test_known_matchups(self):
        i = HAND_INDEX
        self.assertAlmostEqual(class_equity(i["AA"], i["KK"]), 0.8195, delta=0.004)
        self.assertAlmostEqual(class_equity(i["AKs"], i["QQ"]), 0.4604, delta=0.004)
        self.assertAlmostEqual(class_equity(i["AKo"], i["22"]), 0.4735, delta=0.004)
        self.assertAlmostEqual(class_equity(i["TT"], i["AKo"]), 0.568, delta=0.004)

    def test_symmetry(self):
        m = matrix()
        for a in range(0, 169, 7):
            for b in range(0, 169, 5):
                self.assertAlmostEqual(m.eq[a][b] + m.eq[b][a], 1.0, places=3)

    def test_card_removal_counts(self):
        m = matrix()
        i = HAND_INDEX
        self.assertEqual(m.n[i["AA"]][i["AA"]], 6)      # only the two complementary pairs
        self.assertEqual(m.n[i["AA"]][i["KK"]], 36)
        self.assertEqual(m.n[i["AKs"]][i["AKs"]], 12)
        self.assertEqual(m.n[i["AKo"]][i["72o"]], 144)

    def test_vs_range(self):
        eq, prob = eq_vs_range(HAND_INDEX["AA"], parse_range("KK+"))
        # holding two aces, the range is mostly KK and AA is nearly impossible
        self.assertGreater(eq, 0.75)
        self.assertAlmostEqual(prob, 7 / 1225, places=6)

    def test_postflop_exact(self):
        # top set against an overpair on a dry turn: villain has two outs
        res = hand_equity(parse_cards("KhKd"), parse_cards("Ks7d2c9h"), [parse_range("AA")])
        self.assertEqual(res["method"], "exact")
        self.assertAlmostEqual(res["equity"], 1 - 2 / 44, places=3)
        # river is a pure comparison
        res = hand_equity(parse_cards("AhKd"), parse_cards("Ks7d2c9h3s"), [parse_range("KQs, KQo, 77")])
        self.assertEqual(res["method"], "exact")
        # KQ: 8 combos lose to us, 77: 3 combos beat us
        self.assertAlmostEqual(res["equity"], 8 / 11, places=6)

    def test_monte_carlo_close_to_matrix(self):
        res = hand_equity(parse_cards("AhKd"), [], [parse_range("QQ")], iters=30000)
        self.assertAlmostEqual(res["equity"], class_equity(HAND_INDEX["AKo"], HAND_INDEX["QQ"]), delta=0.02)


class ICM(unittest.TestCase):
    def test_matches_brute_force(self):
        rng = random.Random(3)
        for _ in range(25):
            n = rng.randint(2, 7)
            stacks = [rng.choice([120, 500, 1500, 3000, 8000, 20000]) * rng.uniform(0.5, 1.5) for _ in range(n)]
            pays = sorted([rng.uniform(1, 50) for _ in range(rng.randint(1, n))], reverse=True)
            exact = mh_exact(stacks, pays)
            for i in range(n):
                self.assertAlmostEqual(hero_equity(stacks, i, pays), exact[i], delta=1e-4 * max(1, exact[i]))

    def test_classic_example(self):
        vals = [hero_equity([4000, 3000, 2000, 1000], i, [50, 30, 20]) for i in range(4)]
        self.assertAlmostEqual(sum(vals), 100.0, places=3)
        self.assertGreater(vals[0], vals[1])
        self.assertLess(vals[0], 40.0)          # 40% of the chips is worth less than 40% of the pool
        self.assertGreater(vals[3], 10.0)       # the short stack is worth more than its chip share

    def test_field_model(self):
        pays = [50, 30, 20, 10]
        table = [9000, 4000, 2500]
        exact = mh_exact(table + [3000] * 4, pays)
        for i in range(3):
            self.assertAlmostEqual(hero_equity(table, i, pays, 4, 3000), exact[i], places=3)

    def test_big_field_conservation(self):
        pays = default_payouts(500, 75, 500.0)
        self.assertAlmostEqual(sum(pays), 500.0, places=6)
        self.assertEqual(len(pays), 75)
        self.assertTrue(all(a >= b for a, b in zip(pays, pays[1:])))
        # equal stacks: everyone owns an equal share of the prize pool
        v = hero_equity([25000], 0, pays, 199, 25000)
        self.assertAlmostEqual(v, 500.0 / 200, places=3)

    def test_bust_value(self):
        pays = [50, 30, 20]
        self.assertEqual(hero_equity([0, 5000, 5000, 5000], 0, pays), 0.0)   # 4th of 4, unpaid
        self.assertEqual(hero_equity([0, 5000, 5000], 0, pays), 20.0)        # 3rd of 3, paid

    def test_bubble_factor(self):
        pays = default_payouts(500, 75, 500.0)
        stacks = [30000, 60000, 120000, 15000] + [65000] * 5
        bubble = Prizes(pays, field_n=76 - 9, field_stack=65000)
        early = Prizes(pays, field_n=400 - 9, field_stack=12500)
        mid_vs_big = bubble.bubble_factor(stacks, 1, 2)
        self.assertGreater(mid_vs_big, 1.4)
        self.assertGreater(mid_vs_big, bubble.bubble_factor(stacks, 2, 1))  # the big stack risks less
        self.assertLess(early.bubble_factor([12500] * 9, 0, 1), 1.2)
        self.assertEqual(Prizes().bubble_factor(stacks, 1, 2), 1.0)
        # an ITM bonus makes survival even more valuable
        bonus = Prizes(pays, field_n=76 - 9, field_stack=65000, itm_bonus=pays[-1])
        self.assertGreater(bonus.bubble_factor(stacks, 1, 2), mid_vs_big)


class PushFold(unittest.TestCase):
    def test_heads_up_nash(self):
        sol = solve_open_shove(HandSetup([10, 10], 0.5, 1.0), 0, Prizes(), iters=60, use_types=False)
        self.assertAlmostEqual(range_pct(sol.shove_range), 58.3, delta=2.5)
        self.assertAlmostEqual(range_pct(sol.callers[0].call_range), 37.4, delta=2.5)

    def test_position_and_depth_monotone(self):
        widths = [range_pct(nash_push_range(nb, 10)) for nb in (8, 5, 3, 2, 1)]
        self.assertEqual(widths, sorted(widths))
        depth = [range_pct(nash_push_range(2, s)) for s in (5, 10, 15, 20)]
        self.assertEqual(depth, sorted(depth, reverse=True))
        self.assertEqual(nash_push_range(8, 10)[HAND_INDEX["AA"]], 1.0)
        self.assertEqual(nash_push_range(8, 10)[HAND_INDEX["72o"]], 0.0)

    def test_setup_accounting(self):
        s = HandSetup([20, 20, 20], 0.5, 1.0, 0.0, 1.0)   # BTN, SB, BB with a 1bb big-blind ante
        steal = s.fold_out(0)
        self.assertAlmostEqual(sum(steal), 60.0)
        self.assertAlmostEqual(steal[0], 22.5)
        win = s.showdown(0, 2, 0)
        self.assertAlmostEqual(sum(win), 60.0)
        self.assertAlmostEqual(win[2], 0.0)
        self.assertAlmostEqual(win[0], 40.5)
        lose = s.showdown(0, 2, 2)
        self.assertAlmostEqual(lose[0], 1.0)   # hero covered the BB's live stack by the ante


class Preflop(unittest.TestCase):
    def go(self, hand, stack, pos, facing="", players=9, villain=None, prizes=None):
        h, cards = parse_hand(hand)
        return advise(quick_spot(h, cards, stack, players, pos, facing, villain, prizes))

    def test_basics(self):
        for stack in (6, 12, 18, 30, 80):
            for pos in ("UTG", "CO", "BTN", "SB"):
                self.assertNotEqual(self.go("AA", stack, pos).action, "FOLD", (stack, pos))
                self.assertEqual(self.go("72o", stack, "UTG").action, "FOLD")
        self.assertTrue(self.go("AJo", 11.5, "CO").action.startswith("ALL-IN"))
        self.assertEqual(self.go("K9o", 9, "UTG+1").action, "FOLD")
        self.assertEqual(self.go("76s", 60, "UTG").action, "FOLD")
        self.assertTrue(self.go("KQo", 40, "BTN").action.startswith("RAISE"))

    def test_facing_raises(self):
        self.assertTrue(self.go("AQo", 20, "BTN", "HJ raise 2.2bb").action.startswith("ALL-IN"))
        self.assertTrue(self.go("AKo", 60, "SB", "UTG raise 2.5bb").action.startswith("3-BET"))
        self.assertEqual(self.go("88", 45, "BTN", "UTG+1 raise 2.3bb").action, "CALL")
        self.assertEqual(self.go("J4o", 40, "BTN", "UTG raise 2.3bb").action, "FOLD")
        self.assertEqual(self.go("KK", 40, "BTN", "UTG raise 2.2bb, HJ raise 6.5bb").action, "ALL-IN")
        self.assertEqual(self.go("AJo", 40, "BTN", "UTG raise 2.2bb, HJ raise 6.5bb").action, "FOLD")

    def test_a_raiser_who_is_priced_in_is_the_hand_to_beat(self):
        """An all-in over a raise the raiser has to call anyway.  The solver takes one caller at a time: with the
        player behind taken first, his call made the raise dead money and fed on itself, and the small blind
        moved all-in with T4o for 7bb over a first-seat raise to 2.5bb ("40% when called", against a range it
        has 28% against)."""
        from poker_coach import preflop
        from poker_coach.pushfold import Caller
        for hand, action in (("T4o", "FOLD"), ("K9o", "FOLD"), ("JTs", "FOLD"), ("AJo", "ALL-IN"), ("77", "ALL-IN")):
            self.assertEqual(self.go(hand, 7, "SB", "UTG raise 2.5bb").action, action, hand)
        said = " ".join(self.go("T4o", 7, "SB", "UTG raise 2.5bb").numbers)
        self.assertRegex(said, r"when called you have 2[5-9]%")
        # who is taken together: the raiser and his callers once he needs a third of the pot or less
        behind, raiser, flat = (Caller(8, "bb", 0.4, 0.0, 0.0, chip_req=0.36), Caller(0, "utg", 0.3, 0.0, 0.0, chip_req=0.30),
                                Caller(1, "utg1", 0.3, 0.0, 0.0, chip_req=0.29))
        group = lambda flats: [c.idx for c in preflop._taken_together(                 # noqa: E731
            [behind, raiser] + ([flat] if flats else []), 0, flats)]
        self.assertEqual(group({}), [0])
        self.assertEqual(group({1: None}), [0, 1])
        raiser.chip_req = preflop._PRICED_IN + 0.01             # he can still fold: one caller at a time, as before
        self.assertEqual(group({}), [])
        self.assertEqual(group({1: None}), [0, 1])              # ... but never with players who called him in the pot
        raiser.chip_req = 0.0                                   # nothing left to call: placed by the spot itself
        self.assertEqual(group({}), [])
        self.assertEqual(group({1: None}), [])
        # at an ordinary depth nothing moved: the button over a cutoff raise with 20bb
        self.assertTrue(self.go("AJo", 20, "BTN", "CO raise 2.2bb").action.startswith("ALL-IN"))
        self.assertEqual(self.go("K9o", 20, "BTN", "CO raise 2.2bb").action, "FOLD")

    def test_callers_who_are_priced_in_have_hands_too(self):
        """An all-in over a raise and calls, when none of them can fold: the shover has to beat them all.  (Their
        chips were dead money: the button moved all-in with 62% of hands for 11bb over a raise to 4bb and two
        calls.)"""
        from poker_coach.pushfold import beats_all, solve_shove, Caller
        line = "LJ raise 4bb, HJ call, CO call"
        for hand, action in (("K9o", "FOLD"), ("98s", "FOLD"), ("A5o", "FOLD"), ("JTs", "FOLD"), ("TT", "ALL-IN"), ("AKo", "ALL-IN")):
            self.assertEqual(self.go(hand, 11, "BTN", line).action, action, hand)
        self.assertEqual(self.go("T4o", 16, "SB", "UTG raise 4bb, UTG+1 call, UTG+2 call").action, "FOLD")
        self.assertEqual(self.go("K9o", 16, "SB", "UTG raise 4bb, UTG+1 call, UTG+2 call").action, "FOLD")
        # the same a little deeper, where the raiser could fold: 12bb and 13bb are no longer two different games
        for stack in (12, 13, 16):
            for hand, action in (("J8o", "FOLD"), ("K9o", "FOLD"), ("QQ", "ALL-IN")):
                self.assertEqual(self.go(hand, stack, "SB", "HJ raise 2bb, CO call, BTN call").action.split()[0], action.split()[0], (hand, stack))
        said = " ".join(self.go("TT", 11, "BTN", line).numbers)
        self.assertRegex(said, r"when called you have [34]\d%")           # against three hands, not 60% against one
        # the chance against several players, from the equity against each
        self.assertAlmostEqual(beats_all([0.5, 0.5]), 1 / 3)
        self.assertAlmostEqual(beats_all([0.5, 0.5, 0.5]), 1 / 4)
        self.assertAlmostEqual(beats_all([0.4]), 0.4)
        self.assertAlmostEqual(beats_all([0.85, 0.85]), 0.739, places=3)
        self.assertEqual(beats_all([0.3, 0.0]), 0.0)
        # ... is close to the cards dealt out: a cutoff raise and the button's call
        from poker_coach.equity import preflop_equity
        from poker_coach.preflop import flat_range
        from poker_coach.ranges import villain_open_range
        ranges = [villain_open_range(3, "unknown", 40.0), flat_range(3, 2)]
        for hand in ("AJo", "77", "Q5o", "T9s"):
            h = HAND_INDEX[hand]
            exact = preflop_equity(h, None, ranges, iters=12000)
            self.assertAlmostEqual(beats_all([eq_vs_range(h, r)[0] for r in ranges]), exact, delta=0.045, msg=hand)
        # in the solver: one member taken together is the same as that caller taken first
        one = [Caller(1, "raiser", 0.30, 30.0, 0.0, prior=parse_range("22+, A2s+, KTs+, ATo+, KQo")), Caller(2, "bb", 0.45, 24.0, 0.0)]
        plain = solve_shove(8.0, 12.5, one)
        one = [Caller(1, "raiser", 0.30, 30.0, 0.0, prior=parse_range("22+, A2s+, KTs+, ATo+, KQo")), Caller(2, "bb", 0.45, 24.0, 0.0)]
        grouped = solve_shove(8.0, 12.5, one, together=([one[0]], {1: (30.0, 0.0)}))
        for h in (0, 50, 100, 168):
            self.assertAlmostEqual(plain.ev[h], grouped.ev[h], places=9)

    def test_a_re_raise_and_an_all_in_behind_my_raise(self):
        """I raise, one player re-raises and another moves all-in over both: the narrowest range before the
        flop.  (It was priced as a plain all-in over my raise, a range four times as wide: tens moved all-in.)"""
        line = "hero raise 2.3bb, SB raise 8.7bb, BB allin"
        for hand in ("AA", "KK"):
            self.assertNotEqual(self.go(hand, 40, "CO", line).action, "FOLD", hand)
        for hand in ("JJ", "TT", "AKo", "AQs", "KQs"):
            self.assertEqual(self.go(hand, 40, "CO", line).action, "FOLD", hand)
        adv = self.go("KQs", 40, "CO", line)
        self.assertLess(adv.data["villain_pct"], 4)
        self.assertIn("narrowest", " ".join(adv.why))
        self.assertIn("re-raiser still to act", " ".join(adv.numbers))
        # shorter, that all-in is wider: jacks and ace-king go with it, tens do not
        short = "hero raise 2bb, SB raise 7.6bb, BB allin"
        for hand in ("JJ", "AKo"):
            self.assertNotEqual(self.go(hand, 20, "CO", short).action, "FOLD", hand)
        self.assertEqual(self.go("TT", 20, "CO", short).action, "FOLD")
        # from an early seat it is tighter still, and a deep stack goes on with aces and kings only
        self.assertEqual(self.go("QQ", 40, "UTG", line).action, "FOLD")
        self.assertEqual(self.go("QQ", 100, "CO", line).action, "FOLD")
        self.assertNotEqual(self.go("KK", 100, "CO", line).action, "FOLD")
        # the last raise need not be all-in: it is priced as one
        self.assertEqual(self.go("JJ", 100, "CO", "hero raise 2.3bb, SB raise 9bb, BB raise 22bb").action, "FOLD")
        self.assertEqual(self.go("AA", 100, "CO", "hero raise 2.3bb, SB raise 9bb, BB raise 22bb").action, "ALL-IN")
        # a loose player's all-in is wider, a tight player's narrower
        def typed(kind, hand):
            h, cards = parse_hand(hand)
            spot = quick_spot(h, cards, 40, 9, "CO", line)
            spot.types = [kind] * 9
            return advise(spot)
        self.assertEqual((typed("unknown", "QQ").action, typed("unknown", "QQ").confidence), ("ALL-IN", "close"))
        self.assertEqual((typed("loose", "QQ").action, typed("loose", "QQ").confidence), ("ALL-IN", "clear"))
        self.assertEqual(typed("tight", "QQ").action, "FOLD")

    def test_facing_all_in(self):
        self.assertEqual(self.go("A9o", 15, "BB", "SB allin").action, "CALL")
        self.assertEqual(self.go("T4o", 15, "BB", "SB allin").action, "FOLD")
        self.assertEqual(self.go("JJ", 30, "CO", "hero raise 2.2bb, BB allin", villain=14).action, "CALL")

    def test_bubble_tightens_calls(self):
        pays = default_payouts(500, 75)
        bubble = Prizes(pays, field_n=78 - 9, field_stack=25, itm_bonus=pays[-1])
        chips = self.go("AQo", 25, "BB", "BTN allin")
        icm = self.go("AQo", 25, "BB", "BTN allin", prizes=bubble)
        self.assertEqual(chips.action, "CALL")
        self.assertEqual(icm.action, "FOLD")
        self.assertGreater(icm.data["need"], chips.data["need"] + 0.08)
        # aces are still a call on the bubble
        self.assertNotEqual(self.go("AA", 25, "BB", "BTN allin", prizes=bubble).action, "FOLD")

    def test_bubble_shove_is_not_any_two(self):
        pays = default_payouts(500, 75)
        bubble = Prizes(pays, field_n=78 - 9, field_stack=9, itm_bonus=pays[-1])
        spot = quick_spot(parse_hand("72o")[0], None, 9, 9, "BTN", "", None, bubble)
        spot.field_prizes = Prizes(pays, field_n=78 - 9, field_stack=9)
        self.assertEqual(advise(spot).action, "FOLD")

    def test_heads_up_and_short_tables(self):
        self.assertNotEqual(self.go("K8o", 7, "SB", players=6).action, "FOLD")
        self.assertTrue(self.go("Q7s", 30, "SB", players=2).action.startswith("RAISE"))
        self.assertNotEqual(self.go("AKs", 25, "UTG", players=4).action, "FOLD")

    # ---- the review findings (PRE-n), one test each ---------------------------------------------

    @staticmethod
    def table(stacks, hero, hand, acts=(), left=None, paid=150, entrants=1000, away=(), types=None, ante=0.125,
              folded=()):
        """A spot with real stacks (big blinds, in acting order); ``left`` players turns ICM on.

        ``away`` sat out when the hand was dealt; ``folded`` are players who folded after hero's raise (the
        table app hands them to the engine as away, and says who really sat out)."""
        from poker_coach.preflop import Act, Spot
        setup = HandSetup([float(x) for x in stacks], 0.5, 1.0, ante, 0.0)
        n = len(stacks)
        prizes = field = Prizes()
        if left:
            prizes = Prizes(default_payouts(entrants, paid), max(0, left - n), sum(stacks) / n)
            field = Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack)
        acts = [Act(i, kind, setup.live[i] if kind == "allin" else min(float(amount), setup.live[i]))
                for i, kind, amount in acts]
        return Spot(setup=setup, hero=hero, hand=HAND_INDEX[hand], prizes=prizes, field_prizes=field, acts=acts,
                    away=[i in away or i in folded for i in range(n)], types=list(types) if types else [],
                    sitting_out=[i in away for i in range(n)])

    def play(self, *args, **kw):
        return advise(self.table(*args, **kw))

    def opens(self, stacks, hero, away=()):
        out = set()
        for hand in HANDS:
            action = self.play(stacks, hero, hand, away=away).action
            if action.startswith("RAISE") or "ALL-IN" in action:
                out.add(hand)
        return out

    def test_pre_1_the_big_blind_has_one_price_test_for_every_hand(self):
        from poker_coach.preflop import _hand_kind, bb_call_points
        from poker_coach.ranges import villain_open_range
        strong, weak = ("ATs", "AJo", "KQo", "KTs"), ("T2s", "32s", "72s")
        # chips only, far from the money, close to it, the bubble, in the money, a final table
        for stack in (30, 50):
            for left in (None, 400, 185, 152, 100, 8):
                for raiser, size in ((5, 2.2), (6, 3.0), (0, 2.2)):
                    got = {hand: self.play([stack] * 8, 7, hand, [(raiser, "raise", size)], left=left).action
                           for hand in strong + weak}
                    for hand in strong:
                        self.assertNotEqual(got[hand], "FOLD", (stack, left, raiser, hand, got))
        # every hand, in the money and close to it: a fold is never 15 points above the price, and no
        # folded hand has more equity than a called hand that needs as many points
        for left, raiser, size in ((100, 5, 2.2), (185, 5, 2.2), (100, 6, 3.0), (None, 0, 2.2)):
            opened = villain_open_range(7 - raiser)
            dead = 8 * 0.125 + (1.0 if raiser == 6 else 1.5)                     # antes and the blinds
            price = (size - 1.0) / (dead + size + size - 1.0)
            rows = {}
            for index, hand in enumerate(HANDS):
                adv = self.play([30] * 8, 7, hand, [(raiser, "raise", size)], left=left)
                rows[hand] = (adv.action, eq_vs_range(index, opened)[0], _hand_kind(index))
                self.assertAlmostEqual(adv.data["bb_call_need"] + adv.data["bb_call_edge"], rows[hand][1], places=6)
            folds = {h: r for h, r in rows.items() if r[0] == "FOLD"}
            calls = {h: r for h, r in rows.items() if r[0] == "CALL"}
            self.assertTrue(len(calls) > 40 and len(folds) > 20, (left, raiser))
            for hand, (_action, equity, kind) in folds.items():
                self.assertLess(equity, price + 0.15, (left, raiser, hand))
                for other, (_a, other_equity, other_kind) in calls.items():
                    if bb_call_points(kind) <= bb_call_points(other_kind):
                        self.assertLess(equity, other_equity, (left, raiser, hand, other))
        # the points: offsuit hands that are not two big cards need the most, nothing needs more than 15
        self.assertLess(bb_call_points("suited"), bb_call_points("broadway_off"))
        self.assertLess(bb_call_points("broadway_off"), bb_call_points("off"))
        self.assertEqual(bb_call_points("suited"), bb_call_points("suited_conn"))
        self.assertGreater(bb_call_points("suited", 0.08), bb_call_points("suited"))       # ICM asks for more
        self.assertEqual(max(bb_call_points(kind, 0.5, 2) for kind in ("pair", "suited", "broadway_off", "off")), 0.15)
        # against a small blind's raise the big blind acts last after the flop: fewer points
        self.assertLess(bb_call_points("suited", in_position=True), bb_call_points("suited"))
        for hand in ("64s", "54s", "K7o", "A5o"):
            self.assertEqual(self.play([30] * 8, 7, hand, [(6, "raise", 3.0)]).action, "CALL", hand)
        # 25bb or less is the same test: no stronger hand folds where a weaker one calls
        got = {hand: self.play([20] * 8, 7, hand, [(5, "raise", 2.0)], left=400).action for hand in strong + weak}
        self.assertFalse(any(got[hand] == "FOLD" for hand in strong), got)

    def test_pre_2_the_best_hands_never_fold_to_one_reraise_when_deep(self):
        import re
        # the review's hand: cutoff raises, the button re-raises to 7bb, hero holds AKo out of position
        for depth, want in ((46, "ALL-IN"), (50, "ALL-IN"), (60, "ALL-IN"), (61, "CALL"), (100, "CALL")):
            adv = self.play([depth] * 8, 4, "AKo", [(4, "raise", 2.3), (5, "raise", 7.0)])
            self.assertEqual(adv.action, want, depth)
        for left in (None, 152):                                                 # chips only, and on the bubble
            for depth in (46, 60, 61, 100):
                # out of position against the button; in position against the big blind, from the button and UTG
                for hero, villain, three, in_position in ((4, 5, 7.0, False), (5, 7, 9.0, True), (0, 7, 9.0, True)):
                    for hand in ("AA", "KK", "QQ", "AKs", "AKo"):
                        adv = self.play([depth] * 8, hero, hand, [(hero, "raise", 2.3), (villain, "raise", three)],
                                        left=left)
                        key = (left, depth, hero, hand, adv.action)
                        number = float(re.search(r"shove EV ([+-][\d.]+)bb", " ".join(adv.numbers)).group(1))
                        self.assertNotEqual(adv.action, "FOLD", key)
                        if adv.action.startswith("4-BET"):
                            self.assertIn(hand, ("AA", "KK"), key)
                        elif in_position or depth > 60:
                            self.assertEqual(adv.action, "CALL", key)
                        elif abs(number) >= 0.01:                                # out of position, 60bb or less
                            self.assertEqual(adv.action, "ALL-IN" if number > 0 else "CALL", key)
        # the hands below them still fold, and with 45bb or less ace-king's all-in stays the play where it earns
        self.assertEqual(self.play([50] * 8, 4, "AJo", [(4, "raise", 2.3), (5, "raise", 7.0)]).action, "FOLD")
        self.assertEqual(self.play([40] * 8, 4, "AKo", [(4, "raise", 2.3), (5, "raise", 7.0)]).action, "ALL-IN")

    def test_pre_3_a_committed_raiser_is_an_all_in_only_heads_up(self):
        # the button (3bb) raises to 2.2bb, the small blind (30bb) calls, hero is the big blind with 16bb
        stacks = [20, 20, 20, 20, 20, 3, 30, 16]
        acts = [(5, "raise", 2.2), (6, "call", 2.2)]
        for left in (100, None):
            got = {hand: self.play(stacks, 7, hand, acts, left=left) for hand in ("72o", "J4o", "T9s", "A9s")}
            for hand, adv in got.items():
                self.assertIn(adv.action, ("CALL", "FOLD"), (left, hand))
                self.assertLess(adv.data["need"], 0.30, (left, hand))            # the price of what hero adds
            self.assertEqual((got["72o"].action, got["T9s"].action), ("FOLD", "CALL"), left)
        # all-in only with a hand that plays for its whole stack against the caller: TT+ and AK
        got = {hand: self.play(stacks, 7, hand, acts, left=100).action for hand in ("KK", "TT", "99", "AQs")}
        self.assertEqual(got, {"KK": "RE-RAISE ALL-IN (isolate)", "TT": "RE-RAISE ALL-IN (isolate)",
                               "99": "CALL", "AQs": "CALL"})
        # heads-up it stays an all-in: nobody else is in the pot and nobody is left to act
        self.assertEqual(self.play(stacks, 7, "J4o", [(5, "raise", 2.2)], left=100).action, "ALL-IN")
        # players still to act behind hero: UTG (5bb) raises to 2bb, hero on the button with 30bb
        got = {hand: self.play([5, 30, 30, 30, 30, 30, 30, 30], 5, hand, [(0, "raise", 2.0)], left=400).action
               for hand in ("72o", "KJo", "99", "KK")}
        self.assertEqual(got, {"72o": "FOLD", "KJo": "CALL", "99": "RE-RAISE to 12.5bb (isolate)", "KK": "CALL"})

    def test_pre_9_isolating_all_in_only_with_a_short_stack(self):
        allin = [(5, "allin", 0)]
        # small blind 35bb, the button is all-in for 6bb, the big blind has 35bb behind
        got = {hand: self.play([35, 35, 35, 35, 35, 6, 35, 35], 6, hand, allin, left=400)
               for hand in ("K9s", "66", "TT", "A8o", "72o")}
        for hand, adv in got.items():
            self.assertNotIn("ALL-IN", adv.action, hand)
            if adv.action.startswith("RE-RAISE"):
                self.assertEqual(adv.action, "RE-RAISE to 15bb (isolate)", hand)  # 2.5 times the 6bb
                self.assertFalse(any("shove EV" in line for line in adv.numbers), hand)
        self.assertEqual((got["K9s"].action, got["72o"].action), ("CALL", "FOLD"))
        self.assertTrue(got["66"].action.startswith("RE-RAISE to") and got["TT"].action.startswith("RE-RAISE to"))
        # the all-in is hero's raise with 20bb or less, or with 2.5 times the all-in or less
        short = [20, 20, 20, 20, 20, 6, 16, 30]
        adv = self.play(short, 6, "K9s", allin, left=400)
        self.assertEqual(adv.action, "RE-RAISE ALL-IN (isolate)")
        self.assertGreater(adv.data["isolate_ev_bb"], 0.15)
        self.assertTrue(any("shove EV +" in line for line in adv.numbers), adv.numbers)   # the number of this all-in
        self.assertEqual(self.play(short, 6, "T9s", allin, left=400).action, "CALL")       # that all-in loses: call
        self.assertEqual(self.play([20, 20, 20, 20, 20, 12, 28, 40], 6, "TT", allin).action, "RE-RAISE ALL-IN (isolate)")
        for stack in (22, 40, 100):                                               # deeper: never the all-in
            for hand in ("TT", "KJo"):
                adv = self.play([stack] * 5 + [6, stack, stack], 6, hand, allin)
                self.assertNotIn("ALL-IN", adv.action, (stack, hand))
                size = re.search(r"RE-RAISE to ([\d.]+)bb", adv.action)
                self.assertTrue(size is None or float(size.group(1)) == 15.0, (stack, hand, adv.action))
        # very deep the re-raise is small against the stack: UTG all-in for 8bb, hero in the cutoff with 100bb
        deep = [8] + [100] * 7
        self.assertEqual(self.play(deep, 4, "TT", [(0, "allin", 0)]).action, "RE-RAISE to 20bb (isolate)")
        self.assertEqual(self.play(deep, 4, "KJo", [(0, "allin", 0)]).action, "FOLD")
        # king-queen offsuit was a close fold by the price and a margin for the players behind (44% for 46%).  The
        # call of an all-in of 8bb is now read from the exact game, where those players are in the answer: a call
        # worth 0.08bb, and no hand for a re-raise
        adv = self.play(deep, 4, "KQo", [(0, "allin", 0)])
        self.assertEqual(adv.action, "CALL")
        self.assertTrue(adv.data.get("exact") and 0.0 < adv.data["exact_ev"] < 0.2, adv.data)

    def test_pre_10_a_caller_with_chips_is_not_a_second_all_in(self):
        # the button is all-in for 3bb, the small blind (30bb) calls, hero is the big blind with 16bb
        stacks = [20, 20, 20, 20, 20, 3, 30, 16]
        acts = [(5, "allin", 0), (6, "call", 2.875)]
        got = {hand: self.play(stacks, 7, hand, acts, left=100) for hand in ("T9s", "A9s", "99", "72o", "TT", "AKo")}
        for hand in ("T9s", "A9s", "99"):
            self.assertEqual(got[hand].action, "CALL", hand)
        # hero adds 1.9bb to a pot of 7.75bb: about 19%, plus the points for the caller still in
        self.assertTrue(0.22 < got["T9s"].data["need"] < 0.30, got["T9s"].data)
        self.assertEqual(got["72o"].action, "FOLD")
        for hand in ("TT", "AKo"):                                               # the raise is considered
            self.assertTrue(got[hand].action.startswith("RE-RAISE"), (hand, got[hand].action))
        self.assertFalse(any("multi-way all-in" in text for adv in got.values() for text in adv.warnings))
        # hero on the button with 25bb, UTG all-in for 4bb, the cutoff (40bb) calls
        stacks = [4, 20, 20, 20, 40, 25, 20, 20]
        acts = [(0, "allin", 0), (4, "call", 3.875)]
        got = {hand: self.play(stacks, 5, hand, acts, left=100).action for hand in ("AKo", "TT", "AQs", "76s")}
        self.assertEqual(got, {"AKo": "RE-RAISE to 10bb (isolate)", "TT": "RE-RAISE to 10bb (isolate)",
                               "AQs": "CALL", "76s": "FOLD"})
        # a caller who is all-in himself is still a second all-in
        adv = self.play([20, 20, 20, 20, 20, 3, 2.5, 16], 7, "T9s", [(5, "allin", 0), (6, "call", 2.375)], left=100)
        self.assertTrue(any("multi-way all-in" in text for text in adv.warnings), adv.warnings)

    def test_pre_11_an_all_in_over_a_reraise_is_a_narrow_range(self):
        # the button (30bb) re-raises the cutoff's raise to 6.6bb and the cutoff moves all-in
        stacks = [30] * 8
        line = [(4, "raise", 2.2), (5, "raise", 6.6), (4, "allin", 0)]
        adv = self.play(stacks, 5, "AQo", line, left=400)
        self.assertEqual(adv.action, "FOLD")                                     # was a "clear" call for 23bb
        self.assertLess(adv.data["villain_pct"], 5.0)                            # was 17% of hands
        self.assertTrue(any("[TT+, AQs+, AKo]" in text for text in adv.numbers), adv.numbers)
        self.assertEqual(self.play(stacks, 5, "QQ", line, left=400).action, "CALL")
        # a little wider for loose players and for short stacks, tighter for tight ones
        def width(stack, kind):
            types = ["unknown"] * 8
            types[4] = kind
            return self.play([stack] * 8, 5, "QQ", line, types=types).data["villain_pct"]
        self.assertLess(width(30, "nit"), width(30, "tight"))
        self.assertLess(width(30, "tight"), width(30, "unknown"))
        self.assertLess(width(30, "unknown"), width(30, "loose"))
        self.assertLess(width(30, "loose"), width(30, "maniac"))
        self.assertLess(width(30, "unknown"), width(20, "unknown"))
        self.assertLess(width(20, "maniac"), 12.0)
        # a raise the user opened with is still answered as before: a re-shove over an opening range
        opened = self.play(stacks, 5, "AQo", [(5, "raise", 2.2), (7, "allin", 0)], left=400)
        self.assertGreater(opened.data["villain_pct"], 8.0)
        # the first answer and the one after the all-in never disagree, and with 45bb or less a
        # re-raise that is not all-in is made only with a hand that calls that all-in
        seen = set()
        for stack in (30, 40, 60):
            for hero, opener, size in ((5, 4, 2.2), (6, 5, 2.2)):
                for hand in ("QQ", "JJ", "TT", "AKo", "AQo", "KQs", "A5s"):
                    first = self.play([stack] * 8, hero, hand, [(opener, "raise", size)], left=400)
                    key = (stack, hero, hand, first.action)
                    small = re.match(r"3-BET to ([\d.]+)bb", first.action)
                    if stack <= 45:
                        self.assertNotIn("semi-bluff", first.action, key)
                    if not small or "semi-bluff" in first.action:
                        seen.add(first.action.split()[0])
                        continue
                    plans = [text for text in first.numbers if text.startswith("if ")]
                    self.assertEqual(len(plans), 1, key)
                    promised = "do not fold to a 4-bet at this depth" in first.why
                    second = self.play([stack] * 8, hero, hand, [(opener, "raise", size),
                                       (hero, "raise", float(small.group(1))), (opener, "allin", 0)], left=400)
                    self.assertEqual(second.action == "CALL", promised, key)
                    self.assertEqual(" shoves: CALL " in plans[0], promised, key)
                    self.assertIn(second.action, ("CALL", "FOLD"), key)
                    if stack <= 45:
                        self.assertTrue(promised, key)
                    seen.add("small, calls" if promised else "small, folds")
        self.assertTrue({"ALL-IN", "CALL", "FOLD", "small, calls", "small, folds"} <= seen, seen)
        # the review's hands on the button at 30bb: no re-raise of a fifth of the stack that then folds
        for hand in ("KQs", "AJs", "AQo", "TT"):
            self.assertNotIn("3-BET to", self.play(stacks, 5, hand, [(4, "raise", 2.2)], left=400).action, hand)
        # the small blind has no call in its chart against a late raise: all-in when that clearly
        # earns, else fold; but TT+, AQs+ and AK are never folded there, they call
        self.assertEqual(self.play([40] * 8, 6, "AQo", [(5, "raise", 2.2)], left=400).action, "ALL-IN")
        self.assertEqual(self.play([40] * 8, 6, "KQs", [(5, "raise", 2.2)], left=400).action, "FOLD")
        for stack in (30, 40):                                                   # ten places from the money
            for hand in ("JJ", "TT", "AQs", "AKo"):
                adv = self.play([stack] * 8, 6, hand, [(4, "raise", 2.2)], left=160)
                self.assertNotEqual(adv.action, "FOLD", (stack, hand))
                self.assertNotIn("3-BET to", adv.action, (stack, hand))
        self.assertEqual(self.play([40] * 8, 6, "TT", [(4, "raise", 2.2)], left=160).action, "CALL")

    def test_l2_the_plan_under_a_raise_and_the_answer_to_the_all_in_use_one_range(self):
        from poker_coach.preflop import _chart_shift, hero_open_range
        size = re.compile(r"RAISE to ([\d.]+)bb$")
        followed = shifted = closes = 0
        verdicts = set()
        spots = [([27.3, 27.3, 12, 24, 9.5, 27.3], 3, 160, ("AJo", "KQo", "99", "A9s", "KJs")),   # the review's table
                 ([30] * 8, 4, 160, ("AJo", "ATs", "88", "KQs", "AQo", "77")),
                 ([35, 28, 22, 40, 18, 30, 14, 26], 5, 185, ("AJo", "KQo", "A8s", "66", "QJs", "ATo")),
                 ([40, 22, 35, 28, 30, 25, 12, 38], 3, 400, ("AQo", "TT", "KQs", "AJs")),
                 ([30] * 6, 2, None, ("AJo", "99", "KQs")),                                 # chips only
                 ([38, 30, 26, 30], 1, 152, ("ATs", "88", "KQo"))]
        for stacks, hero, left, hands in spots:
            n = len(stacks)
            for hand in hands:
                first = self.play(stacks, hero, hand, left=left)
                found = size.match(first.action)
                if not found or not first.data.get("plan"):
                    continue
                spot = self.table(stacks, hero, hand, left=left)
                behind = list(range(hero + 1, n))
                shifted += _chart_shift(spot, behind)[0] != 0
                for entry in first.data["plan"]:
                    who = entry["idx"]
                    # hero raises, the players between fold, this player moves all-in, the rest fold
                    line = [(hero, "raise", float(found.group(1))), (who, "allin", 0)]
                    second = self.play(stacks, hero, hand, line, left=left, folded=range(hero + 1, who))
                    key = (stacks, hero, hand, left, who, first.action, second.action)
                    self.assertAlmostEqual(second.data["need"], entry["need"], places=9, msg=key)
                    self.assertAlmostEqual(second.data["equity"], entry["eq"], places=9, msg=key)
                    self.assertEqual(second.action == "CALL", entry["call"], key)
                    self.assertEqual(second.confidence == "close", abs(entry["edge"]) < 0.02, key)
                    text = next(t for t in first.numbers if t.startswith(f"if {entry['pos']} "))
                    self.assertIn(" shoves: CALL " if entry["call"] else " shoves: FOLD ", text, key)
                    followed += 1
                    closes += second.confidence == "close"
                    verdicts.add(second.action)
        self.assertGreaterEqual(followed, 25)
        self.assertGreaterEqual(shifted, 5)             # spots where ICM moves hero's opening row: the old mismatch
        self.assertEqual(verdicts, {"CALL", "FOLD"})
        # the one range: the row first_in opens with, shifted for ICM, by the players who were there at the raise
        spot = self.table([27.3, 27.3, 12, 24, 9.5, 27.3], 3, "AJo", left=160)
        shift = _chart_shift(spot, [4, 5])[0]
        self.assertGreater(shift, 0)
        self.assertEqual(hero_open_range(spot), rfi_range(2, 24.0 - 0.125, shift))
        later = self.table([27.3, 27.3, 12, 24, 9.5, 27.3], 3, "AJo", [(3, "raise", 2.0), (5, "allin", 0)], left=160,
                           folded=[4])
        self.assertEqual(hero_open_range(later), hero_open_range(spot))     # the small blind folded since: no matter
        self.assertNotEqual(hero_open_range(spot), rfi_range(2, 24.0 - 0.125))

    def test_l4_the_small_blind_re_raised_by_the_big_blind_is_out_of_position(self):
        from poker_coach.preflop import _acts_after
        spot = self.table([60] * 8, 6, "QQ")
        order = sorted(range(8), key=lambda i: sum(_acts_after(spot, i, j) for j in range(8) if j != i))
        self.assertEqual([spot.pos(i) for i in order], ["SB", "BB", "UTG", "UTG+1", "LJ", "HJ", "CO", "BTN"])
        heads_up = self.table([60, 60], 0, "QQ")
        self.assertTrue(_acts_after(heads_up, 0, 1))                               # the button acts last
        line = [(6, "raise", 3.0), (7, "raise", 9.0)]                              # small blind raises, big blind re-raises
        for depth in (50, 60, 80, 100):
            for hand in ("QQ", "AKs", "AKo", "99", "AJs", "KQs"):
                adv = self.play([depth] * 8, 6, hand, line)
                text = " ".join(adv.why)
                self.assertNotIn("in position", text, (depth, hand))
                if hand in ("QQ", "AKs", "AKo"):
                    # never folded; all-in with 60bb or less when that earns, as from any seat out of position
                    self.assertEqual(adv.action, "ALL-IN" if depth <= 60 else "CALL", (depth, hand))
                    if adv.action == "CALL":
                        self.assertIn("out of position", text, (depth, hand))
        # the same hand from the button, and heads-up from the small blind, is in position
        self.assertIn("in position", " ".join(self.play([80] * 8, 5, "QQ", [(5, "raise", 2.3), (7, "raise", 9.0)]).why))
        self.assertIn("in position", " ".join(self.play([80, 80], 0, "QQ", [(0, "raise", 2.2), (1, "raise", 7.0)]).why))
        # out of position the thin calls go: 99 called the re-raise "in position" before
        self.assertEqual(self.play([100] * 8, 6, "99", line).action, "FOLD")
        self.assertEqual(self.play([100] * 8, 5, "99", [(5, "raise", 2.3), (7, "raise", 9.0)]).action, "CALL")

    def test_pre_18_a_blind_sitting_out_never_tightens_the_opening_range(self):
        for players in (8, 6):
            button, small, big = players - 3, players - 2, players - 1
            stacks = [50] * players
            own = self.opens(stacks, button)
            for away in ({big}, {small}):
                self.assertTrue(own <= self.opens(stacks, button, away), (players, away))
            cutoff = self.opens(stacks, button - 1)
            one_away = self.opens(stacks, button - 1, {big})
            self.assertTrue(cutoff < one_away, players)                          # one opponent fewer: wider
            # fewer active players behind never means fewer hands
            self.assertTrue(one_away <= self.opens(stacks, button - 1, {button, big}), players)
        # the hands the review saw folded on the button, at 30bb; the small blind itself keeps its own row
        for hand in ("K3s", "Q5s", "K8o", "54s", "A3o", "A2o"):
            for away in ({7}, {6}):
                self.assertTrue(self.play([30] * 8, 5, hand, away=away).action.startswith("RAISE"), (hand, away))
        self.assertEqual(self.play([30] * 8, 6, "K3s").action, "FOLD")

    def test_a_blind_posted_all_in_is_not_a_caller_who_stops_the_others(self):
        # The big blind has 0.6bb: all of it is in as his blind.  The solver listed him as a caller who
        # needs nothing to call, and took the players behind a caller to fold: the raiser "never called",
        # and 72o over an early raise read +1.45bb for 20bb.
        from poker_coach import pushfold
        from poker_coach.preflop import _posted_all_in, solve_open_shove, solve_reshove
        short_bb = [20.0] * 7 + [0.6]
        raised = [(0, "raise", 2.2)]
        for left in (None, 400):
            adv = self.play(short_bb, 6, "72o", raised, left=left)
            self.assertEqual(adv.action, "FOLD", left)
            self.assertLess(adv.data["reshove_ev_bb"], -1.0, left)
            self.assertFalse(any("everyone folds 0%" in line for line in adv.numbers), adv.numbers)
            full = self.play([20.0] * 8, 6, "72o", raised, left=left)
            self.assertLess(abs(adv.data["reshove_ev_bb"] - full.data["reshove_ev_bb"]), 1.0)    # near the usual table
        self.assertIn("ALL-IN", self.play(short_bb, 6, "QQ", raised, left=400).action)
        setup = HandSetup(short_bb, 0.5, 1.0, 0.125)
        self.assertEqual(_posted_all_in(setup, 6), [7])
        self.assertEqual(_posted_all_in(HandSetup([20.0] * 8, 0.5, 1.0, 0.125), 6), [])
        self.assertEqual(_posted_all_in(setup, 6, bets={7: 0.475}), [])          # a bet of his own: he is a player
        # the raiser can call again: the solution names him among the callers, with a real range
        sol = solve_reshove(setup, 6, 0, 2.2, Prizes(), opener_range=parse_range("77+, ATs+, KQs, AJo+"))
        self.assertEqual([c.idx for c in sol.callers], [0])
        self.assertGreater(sol.fold_equity[HAND_INDEX["72o"]], 0.3)
        # first in with the small blind all-in from posting: the big blind behind him can still call
        setup = HandSetup([20.0] * 6 + [0.3, 20.0], 0.5, 1.0, 0.125)
        sol = solve_open_shove(setup, 5, Prizes())
        self.assertEqual([c.idx for c in sol.callers], [7])
        self.assertGreater(sum(sol.caller(7).call_range), 5)
        self.assertEqual(self.play([20.0] * 6 + [0.3, 20.0], 5, "72o").action, "FOLD")
        # with every stack whole the wrappers give the solver's own numbers.  (With an ante the exact game of the
        # short stacks has not got: a quarter of a big blind from every player.  With an eighth the all-in first in
        # is read from that game, poker_coach/short.py, and is no longer the solver's.)
        whole = HandSetup([12.0] * 8, 0.5, 1.0, 0.25)
        self.assertEqual(solve_open_shove(whole, 5, Prizes()).ev, pushfold.solve_open_shove(whole, 5, Prizes()).ev)
        eighth = solve_open_shove(HandSetup([12.0] * 8, 0.5, 1.0, 0.125), 5, Prizes())
        self.assertTrue(eighth.exact)
        self.assertNotEqual(eighth.ev, pushfold.solve_open_shove(HandSetup([12.0] * 8, 0.5, 1.0, 0.125), 5, Prizes()).ev)
        ours = solve_reshove(whole, 6, 4, 2.0, Prizes(), opener_range=parse_range("22+, A2s+, KTs+, ATo+"))
        theirs = pushfold.solve_reshove(whole, 6, 4, 2.0, Prizes(), opener_range=parse_range("22+, A2s+, KTs+, ATo+"))
        self.assertEqual(ours.ev, theirs.ev)

    def test_two_players_who_are_in_for_hero_s_stack_are_two_all_ins(self):
        # The hijack is all-in for 24.7bb and the small blind re-raises to 74bb: hero in the big blind, with
        # 15.5bb, can call all-in or fold.  It was priced as an all-in of his own with the second player
        # folding: "shove EV +40bb" for a 15bb stack, and +12bb beside a fold of Q4o.
        stacks = [40, 40, 24.7, 40, 40, 90, 15.5]
        acts = [(2, "allin", 0), (5, "raise", 74.2)]
        for hand, action in (("Q4o", "FOLD"), ("JJ", "CALL"), ("AA", "CALL")):
            adv = self.play(stacks, 6, hand, acts, left=260)
            self.assertEqual(adv.action, action, hand)
            self.assertTrue(any("equity vs both ranges" in line for line in adv.numbers), adv.numbers)
            self.assertFalse(any("shove EV" in line for line in adv.numbers), adv.numbers)
        # the price is the pot hero can win: of a bigger all-in only what his own stack matches.  The big blind
        # with 9.6bb against all-ins of 65, 30 and 20bb puts in 8.6bb to win about 31: 23%, not 9%
        adv = self.play([65, 30, 20, 40, 40, 40, 40, 40, 9.6], 8, "QJs", [(0, "allin", 0), (1, "allin", 0), (2, "allin", 0)])
        def need(adv):
            return int(re.search(r"need about (\d+)%", " | ".join(adv.numbers)).group(1))

        self.assertEqual(adv.action, "FOLD")
        self.assertTrue(20 <= need(adv) <= 26, adv.numbers)
        # hero covers both: the whole of each all-in is in his pot, as before
        adv = self.play([20, 30, 40, 40, 40, 40, 40, 80], 7, "KK", [(0, "allin", 0), (1, "allin", 0)])
        self.assertEqual(adv.action, "CALL")
        self.assertTrue(34 <= need(adv) <= 42, adv.numbers)

    def test_a_raise_over_an_all_in_is_not_a_re_raise_over_a_full_raise(self):
        # under the gun is all-in for 4bb and the cutoff raises to 10bb: the cutoff holds the hands that play
        # against a 4bb all-in (about one hand in six), not the 3% that re-raise an early raise; and he still
        # decides when hero moves in (the all-in player is asked last, he is in whatever happens)
        stacks = [4, 40, 40, 40, 40, 40, 40, 40]
        acts = [(0, "allin", 0), (4, "raise", 10)]
        got = {hand: self.play(stacks, 5, hand, acts, left=400) for hand in ("QQ", "AKo", "TT", "ATo", "K5s", "72o")}
        # ... so with 45bb or less a hand that is ahead of those hands moves all-in when the number clears twice
        # the usual bar: tens earn about +5bb here (dead money: the 4bb all-in and the 10bb raise), and were
        # folded while only JJ+ and ace-king ever played against "a raise and a re-raise"
        self.assertEqual({hand: adv.action for hand, adv in got.items()},
                         {"QQ": "ALL-IN", "AKo": "ALL-IN", "TT": "ALL-IN", "ATo": "FOLD", "K5s": "FOLD", "72o": "FOLD"})
        self.assertTrue(any("raised over it" in line for line in got["TT"].why), got["TT"].why)
        self.assertFalse(any("raised over it" in line for line in got["QQ"].why), got["QQ"].why)
        # a re-raise over a full raise keeps the list: tens fold there, whatever the number
        self.assertEqual(self.play([40] * 8, 5, "TT", [(0, "raise", 2.2), (4, "raise", 7)], left=400).action, "FOLD")
        # and deeper than 45bb the rule does not apply
        deep = [4] + [70] * 7
        self.assertEqual(self.play(deep, 5, "TT", acts, left=400).action, "FOLD")
        # The hands that raise over an all-in are read from the hands that call it, and with this ante (an eighth
        # of a big blind a player) those are the exact game's (poker_coach/short.py): a player with others behind
        # him calls tighter than the price says, and tighter the bigger the all-in.  Against a 6bb all-in and a
        # raise to 15bb that is one hand in nine (the engine's own solver said one in six, and tens moved in):
        # tens are behind the better half of them and fold, and JJ+ and ace-king are all that plays
        bigger = [(0, "allin", 0), (4, "raise", 15)]
        six = {hand: self.play([6] + [40] * 7, 5, hand, bigger, left=400) for hand in ("JJ", "TT", "AKo", "AQs")}
        self.assertEqual({hand: adv.action for hand, adv in six.items()}, {"JJ": "ALL-IN", "TT": "FOLD", "AKo": "ALL-IN", "AQs": "FOLD"})
        self.assertTrue(any("3-bettor's range ~11." in line for line in six["TT"].numbers), six["TT"].numbers)
        self.assertTrue(any("against the better half of them this hand has only" in line for line in six["TT"].why), six["TT"].why)
        self.assertTrue(any("3-bettor's range ~1" in line for line in got["QQ"].numbers), got["QQ"].numbers)   # 10 to 19%
        ev = [line for line in got["72o"].numbers if "shove EV" in line][0]
        self.assertIn("shove EV -", ev)                                 # 72o for 40bb is a loss, not dead money won
        # a re-raise over an ordinary raise is read as before
        adv = self.play([40] * 8, 5, "QQ", [(0, "raise", 2.2), (4, "raise", 7)], left=400)
        self.assertTrue(any("3-bettor's range ~3" in line or "3-bettor's range ~4" in line for line in adv.numbers), adv.numbers)

    def test_a_tight_player_who_raises_over_an_all_in_is_not_read_as_raising_wide(self):
        # under the gun is all-in for 3bb, the cutoff raises to 7bb, hero is the big blind with 30bb.  With no read
        # the cutoff is taken to hold about 21% of hands, and nines, tens and ace-queen suited move all-in.  The tag
        # did not move that range, so the same hands moved in against a cutoff tagged nit: by the pot arithmetic
        # eights lose about 8bb against TT+, AQs+ and AKo (33%).  Against a nit or a tight player only the list plays
        stacks, acts = [3] + [30] * 7, [(0, "allin", 0), (4, "raise", 7)]

        def tagged(tag):
            return ["unknown"] * 4 + [tag] + ["unknown"] * 3

        # (eights are ahead of every hand that might raise there, 55%, but not of the better half of them: the
        #  estimate is the widest reading, so they fold whoever raised)
        adv = self.play(stacks, 7, "88", acts)
        self.assertEqual(adv.action, "FOLD")
        self.assertTrue(any("against the better half of them this hand has only" in line for line in adv.why), adv.why)
        # The estimate for a player with no read is three quarters of the hands that call that all-in.  With this
        # ante those are the exact game's (21% here); a tag as strong as nit takes the whole spot to the engine's
        # own solver, which has most hands calling 3bb (half of all hands, the most the estimate may be)
        no_read = {"nit": "~50.0%", "tight": "~20.9%"}
        for hand in ("99", "TT", "AQs"):
            self.assertEqual(self.play(stacks, 7, hand, acts).action, "ALL-IN", hand)        # no read: as before
            self.assertEqual(self.play(stacks, 7, hand, acts, types=tagged("lag")).action, "ALL-IN", hand)
            for tag in ("nit", "tight"):
                adv = self.play(stacks, 7, hand, acts, types=tagged(tag))
                self.assertEqual(adv.action, "FOLD", (hand, tag))
                self.assertFalse(any("raised over it" in line for line in adv.why), adv.why)
                # the reason is the tag, not "only 63% against the hands that raise" (63% is not "only")
                self.assertTrue(any(line.startswith(f"CO is {tag}: ") for line in adv.why), adv.why)
                self.assertFalse(any("has only" in line for line in adv.why), adv.why)
                # ... and the range line says whose range it shows: the estimate for a player with no read
                self.assertTrue(adv.numbers[0].startswith(f"a raise over an all-in from a player with no read: {no_read[tag]}"),
                                adv.numbers)
                self.assertNotIn("3-bettor's range", adv.numbers[0])
        for tag in ("nit", "tight"):                                                        # the list, by the number
            self.assertEqual(self.play(stacks, 7, "KK", acts, types=tagged(tag)).action, "ALL-IN")
            self.assertEqual(self.play(stacks, 7, "QQ", acts, types=tagged(tag)).action, "ALL-IN")
        # a hand behind even the wide range keeps its own sentence
        adv = self.play(stacks, 7, "66", acts, types=tagged("tight"))
        self.assertEqual(adv.action, "FOLD")
        self.assertTrue(any("has only 51%" in line for line in adv.why), adv.why)
        # a bigger all-in is called by fewer hands, and fewer hands are ahead of them: against 5bb and a raise to
        # 11bb (13% of hands, where the engine's own solver said 22%) nines, tens and ace-queen fold with no read
        five = [5] + [30] * 7, 7
        for hand, action in (("99", "FOLD"), ("TT", "FOLD"), ("AQs", "FOLD"), ("JJ", "ALL-IN"), ("AKo", "ALL-IN")):
            self.assertEqual(self.play(*five, hand, [(0, "allin", 0), (4, "raise", 11)]).action, action, hand)
        # the all-in the rule makes carries its bar (+1.00bb, twice the usual), for the table app's "close" sentence
        self.assertEqual(self.play(stacks, 7, "TT", acts).data.get("allin_bar_bb"), 1.0)
        self.assertNotIn("allin_bar_bb", self.play(stacks, 7, "QQ", acts).data)

    def test_a_fold_ahead_of_the_price_of_a_call_is_marked_close(self):
        # queens raised under the gun, re-raised by the big blind, 35bb: on chips a call; with prizes counted the
        # hand is ahead of the price and the risk premium by less than the 10 points that make it a call
        acts = [(0, "raise", 2.2), (7, "raise", 8.4)]
        self.assertEqual(self.play([35] * 8, 0, "QQ", acts).action, "CALL")
        adv = self.play([35] * 8, 0, "QQ", acts, left=400)
        self.assertEqual((adv.action, adv.confidence), ("FOLD", "close"))
        self.assertTrue(any(line.startswith("CALL is close: ") and "with the prizes counted" in line for line in adv.alt),
                        adv.alt)
        need, have, prizes = adv.data["close_call"]
        self.assertTrue(0.03 <= have - need < 0.10 and prizes, adv.data)
        # on the bubble the hand is behind the price with the premium: a fold, and not a close one by this rule
        adv = self.play([35] * 8, 0, "QQ", acts, left=152)
        self.assertEqual(adv.action, "FOLD")
        self.assertNotIn("close_call", adv.data)

    # ---- the verifier's engine candidates (E3), one test each -----------------------------------

    def test_e3_a_a_raise_before_the_flop_is_shown_as_an_amount_that_can_be_put_in(self):
        # The engine sizes a raise in tenths of a big blind ("RAISE to 2.3bb"); the table app shows it in chips.
        # At 300/600 that is 1,380.  At 10/25 it would be 57.5: the app must show a whole chip, the two numbers
        # of its headline must agree, and the table must take the amount when the user follows it.
        from poker_coach.app import advice as A
        from poker_coach.app.model import Session

        def table(sb, bb, ante, stack_bb, hero, cards, acts=()):
            n = 8
            seat = lambda index: (index - hero) % n + 1                     # noqa: E731  (hero is seat 1)
            s = Session(save=False)
            s.do("new_session", mode="tournament", size=n, start_stack=10000, button=seat(n - 3))
            s.do("set_level", text=f"{sb}/{bb}/{ante}")
            s.do("set_stacks", values=[stack_bb * bb] * n)
            s.do("set_tournament", remaining=400, paid=150, entrants=1000, start_stack="")
            s.do("deal", hero_cards=cards)
            for index, kind, amount in acts:
                s.do("act", seat=seat(index), kind=kind, amount=amount)
            return s

        seen = set()
        for sb, bb, ante in ((300, 600, 75), (10, 25, 3), (4, 8, 1), (6, 12, 2), (35, 75, 10), (60, 125, 15), (1, 3, 0)):
            spots = [(stack, 5, "AsKd", ()) for stack in (60, 30, 20)]          # the button raises first
            spots.append((60, 5, "AsAd", ((3, "raise", int(round(2.2 * bb))),)))   # ... and re-raises a raise
            spots.append((60, 7, "AsAd", ((1, "call", None), (2, "call", None))))  # the big blind raises two callers
            for stack, hero, cards, acts in spots:
                s = table(sb, bb, ante, stack, hero, cards, acts)
                head = A.advise(s)["headline"]
                where = (sb, bb, ante, stack, cards, head)
                self.assertIn(head["verb"], ("RAISE", "RE-RAISE"), where)
                to = head["follow"]["to"]
                self.assertEqual(to, int(to), where)                                # a whole number of chips
                self.assertTrue(head["size_text"].endswith(f"{int(to):,}"), where)   # the chips on the screen
                shown = float(re.search(r"TO ([\d.]+)BB", head["size_text"]).group(1))
                self.assertAlmostEqual(shown, to / bb, delta=0.051, msg=where)       # ... and their big blinds
                if (2.2 * bb) % 1 or (2.3 * bb) % 1:
                    seen.add(bb)
                s.do("act", seat=1, kind="raise", amount=to)                        # the table takes it
        self.assertEqual(seen, {25, 8, 12, 75, 125, 3})       # levels where 2.2bb or 2.3bb is not a whole chip
        # the engine's own sentence stays in tenths of a big blind
        self.assertRegex(self.go("AKo", 60, "BTN", players=8).action, r"^RAISE to \d+\.\dbb$")

    def test_e3_b_the_big_blind_calls_in_the_order_of_equity_not_of_rank(self):
        # The sweep's two spots: 8 players on the bubble, 12 and 18bb, under the gun raises to 2bb and the big
        # blind folds 94s where it calls 93s.  That is the price test, not a slip of a rule: against a range that
        # holds A5s and A4s but no A3s, 93s has the better equity (the four is dominated and one of them is
        # gone), and the price falls between the two.  Within one kind of hand a call never has less equity
        # than a fold, so no hand is ever folded where a hand that is weaker AGAINST THIS RANGE calls.
        from poker_coach.preflop import _hand_kind
        from poker_coach.ranges import villain_open_range
        opened = villain_open_range(7)
        equity = {hand: eq_vs_range(HAND_INDEX[hand], opened)[0] for hand in HANDS}
        self.assertTrue(parse_range("A5s-A4s")[HAND_INDEX["A4s"]] and format_range(opened).count("A5s-A4s"))
        self.assertGreater(equity["93s"], equity["94s"])
        self.assertLess(equity["93s"] - equity["94s"], 0.003)                  # by a sixth of a point
        # the suited hands ten-high and lower (the price falls among them), and three offsuit ones
        low = [h for h in HANDS if h.endswith("s") and h[0] in "T98765432"] + ["T9o", "98o", "87o"]
        self.assertTrue(all(_hand_kind(HAND_INDEX[h]) in ("suited", "suited_conn") for h in low[:-3]))
        for stack, hands in ((12, low), (18, ["95s", "94s", "93s", "92s"])):
            got = {hand: self.play([stack] * 8, 7, hand, [(0, "raise", 2.0)], left=160) for hand in hands}
            self.assertEqual((got["94s"].action, got["93s"].action), ("FOLD", "CALL"), stack)
            self.assertLess(abs(got["94s"].data["bb_call_edge"]), 0.002)       # 94s misses the price by 0.07 points
            suited = [h for h in hands if h.endswith("s")]
            calls = [equity[h] for h in suited if got[h].action == "CALL"]
            folds = [equity[h] for h in suited if got[h].action == "FOLD"]
            self.assertEqual(len(calls) + len(folds), len(suited), stack)       # (nothing ten-high moves all-in here)
            self.assertGreater(min(calls), max(folds), stack)
            # and every call or fold is the price test's own verdict
            for hand, adv in got.items():
                self.assertEqual(adv.action == "CALL", adv.data["bb_call_edge"] >= 0, (stack, hand))

    def test_e3_c_a_fold_beside_a_positive_shove_number_says_it_is_the_charts(self):
        # Small blind, first in, 22bb, A2o: the engine prints the all-in's number (it solves the small blind's
        # all-in up to 25bb) and folds.  The fold is a rule: above 20bb the small blind raises or folds from its
        # chart, and A2o is not on it (A4o+).  The reason has to say so beside a number that says "+1.16bb".
        adv = self.go("A2o", 22, "SB", players=8)
        self.assertEqual(adv.action, "FOLD")
        number = [line for line in adv.numbers if line.startswith("shove EV")][0]
        self.assertRegex(number, r"shove EV \+\d")
        self.assertIn("outside the TAG opening range", adv.why[0])          # the table app shows the first reason
        rule = [line for line in adv.why if "the plan is raise or fold" in line]
        self.assertEqual(len(rule), 1, adv.why)
        self.assertIn(re.search(r"shove EV (\+\d+\.\d+)bb", number).group(1), rule[0])    # the same number
        self.assertTrue(adv.data.get("fold_by_chart"))
        self.assertNotRegex(" ".join(adv.why), r"\b(do not|never) fold\b")  # (the app reads those words as a plan)
        # with 20bb the same hand is the all-in the number promises, and nothing needs explaining
        short = self.go("A2o", 20, "SB", players=8)
        self.assertEqual(short.action, "ALL-IN")
        self.assertFalse(any("raise or fold" in line for line in short.why))
        # a hand of the chart raises, a hand whose all-in loses folds: neither gets the sentence
        for hand, action in (("A4o", "RAISE"), ("72o", "FOLD")):
            other = self.go(hand, 22, "SB", players=8)
            self.assertTrue(other.action.startswith(action), (hand, other.action))
            self.assertFalse(any("raise or fold" in line for line in other.why), (hand, other.why))
            self.assertFalse(other.data.get("fold_by_chart"))
        # the other seats have the same rule from 17 to 20bb
        utg = self.go("A9s", 17, "UTG", players=8)
        self.assertEqual(utg.action, "FOLD")
        self.assertTrue(any("the plan is raise or fold" in line for line in utg.why), utg.why)

    # ---- the final gate: premium hands against one re-raise, and a raise and a re-raise in front ----

    @staticmethod
    def gate_prizes(left, itm=False, players=8, stack=45.0):
        """The prize model of ``quick --remaining <left> --paid 150 --entrants 1000`` (``--goal itm`` or balanced)."""
        pays = default_payouts(1000, 150)
        return Prizes(pays, left - players, stack, itm_bonus=pays[-1] if itm and left > len(pays) else 0.0)

    @staticmethod
    def shove_number(adv):
        return float(re.search(r"shove EV ([+-][\d.]+)bb", " ".join(adv.numbers)).group(1))

    def test_gate_1_a_hand_far_ahead_of_the_price_is_never_folded_to_one_re_raise(self):
        from poker_coach import preflop
        from poker_coach.preflop import _icm_pressure
        from poker_coach.ranges import threebet_range
        _NEVER_FOLD, _NEVER_FOLD_EDGE = parse_range("TT+, AQs+, AKo"), 0.10         # the rule, as the sheet says it

        def edge(spot, hero, villain, open_to, three):
            """Equity against the re-raiser's range, less the price of the call and the risk premium."""
            equity = eq_vs_range(spot.hand, threebet_range(max(1, spot.nb(hero))))[0]
            pot = sum(spot.setup.antes) + sum(spot.setup.invested({hero: open_to, villain: three}))
            return equity - (three - open_to) / (pot + three - open_to) - _icm_pressure(spot, [villain])[0]

        # The hand that was found: queens raised from the hijack with 45bb, the big blind re-raises to 8.7bb,
        # 400 left of 1,000 and 150 paid.  53% against the range the engine gives the re-raiser, the call needs
        # 34%: FOLD "[standard]" beside "4-bet shove EV +0.03bb", where AKo and KK moved all-in.
        line = "hero raise 2.3bb, BB raise 8.7bb"
        for itm in (False, True):
            for facing in (line, "hero raise 2.3bb, BTN raise 6.9bb"):      # ... and out of position against the button
                adv = self.go("QQ", 45, "HJ", facing, players=8, prizes=self.gate_prizes(400, itm))
                text = " ".join(adv.why)
                self.assertEqual((adv.action, adv.confidence), ("CALL", "standard"), (itm, facing, text))
                self.assertIn("too far ahead of the price to fold to one re-raise: 53% against their range", text)
                self.assertIn("with prizes counted", text)             # the all-in is thin, or does not earn
                self.assertIn("after the flop the stack goes in with an overpair, top pair or better", text)
                self.assertLessEqual(self.shove_number(adv), 0.5, (itm, facing))
        self.assertEqual(self.go("QQ", 35, "HJ", line, players=8, prizes=self.gate_prizes(400, stack=35)).action, "CALL")
        # where the all-in clears the engine's bar it stays the play: on chips, and for the hands that had it
        self.assertEqual(self.go("QQ", 45, "HJ", line, players=8).action, "ALL-IN")
        self.assertEqual(self.go("AKo", 45, "HJ", line, players=8, prizes=self.gate_prizes(400)).action, "ALL-IN")
        # the risk premium stays in the test: on the bubble, against a stack that covers hero, queens still fold
        for itm in (False, True):
            adv = self.go("QQ", 45, "HJ", line, players=8, prizes=self.gate_prizes(152, itm))
            self.assertEqual(adv.action, "FOLD", itm)
        # a call that would leave less than the pot behind is made as the all-in (while that all-in does not lose)
        reraise = [(0, "raise", 2.2), (7, "raise", 8.4)]                   # under the gun raises, the big blind re-raises
        short = self.play([24] * 8, 0, "QQ", reraise)
        self.assertEqual(short.action, "ALL-IN")
        self.assertIn("a call would leave less than the pot behind", " ".join(short.why))
        self.assertGreater(self.shove_number(short), 0.0)
        for stack in (26, 30, 35):
            self.assertEqual(self.play([stack] * 8, 0, "QQ", reraise).action, "CALL", stack)
        # The rule is for the hands that are too good to fold (TT+, AQs+, AKo).  A small pair or a weak ace has
        # the 10 points on paper too, and keeps the old answer: out of position it does not get them.
        button = [(4, "raise", 2.2), (5, "raise", 6.6)]                    # the cutoff raises, the button re-raises
        for hand in ("99", "66", "22", "ATs", "AQo"):
            spot = self.table([35] * 8, 4, hand, button)
            self.assertGreaterEqual(edge(spot, 4, 5, 2.2, 6.6), _NEVER_FOLD_EDGE, hand)
            self.assertLess(_NEVER_FOLD[spot.hand], 0.5, hand)
            self.assertEqual(advise(spot).action, "FOLD", hand)
        # ... and for ONE re-raise: a player who called it, or a second re-raise, and the old answer stands
        called = self.play([45] * 8, 0, "QQ", [(0, "raise", 2.3), (4, "raise", 6.9), (5, "call", 6.9)], left=400)
        twice = self.play([45] * 8, 0, "QQ", [(0, "raise", 2.3), (4, "raise", 6.9), (5, "raise", 14.0)], left=400)
        alone = self.play([45] * 8, 0, "QQ", [(0, "raise", 2.3), (4, "raise", 6.9)], left=400)
        self.assertEqual((called.action, twice.action, alone.action), ("FOLD", "FOLD", "CALL"))
        # Every stage and depth: no hand of that list is folded with 10 points over the price and the risk
        # premium, by the engine's own numbers.  (Deeper than 45bb the old call test, 78% of the equity out of
        # position, folded JJ, TT and AQs there as well.)
        folds = 0
        for hero, villain, open_to, three in ((3, 7, 2.3, 8.7), (3, 5, 2.3, 6.9), (0, 7, 2.3, 8.7), (2, 5, 2.3, 6.9)):
            for stack in (30, 45, 55):
                for left in (None, 400, 152):
                    for hand in ("TT", "JJ", "QQ", "AKo", "AQs"):
                        spot = self.table([stack] * 8, hero, hand, [(hero, "raise", open_to), (villain, "raise", three)],
                                          left=left)
                        adv = advise(spot)
                        if adv.action != "FOLD":
                            continue
                        folds += 1
                        self.assertLess(edge(spot, hero, villain, open_to, three), _NEVER_FOLD_EDGE,
                                        (hero, villain, stack, left, hand))
        self.assertGreater(folds, 20)                                       # the bubble, and the hands that are behind
        self.assertEqual((preflop._NEVER_FOLD, preflop._NEVER_FOLD_EDGE), (_NEVER_FOLD, _NEVER_FOLD_EDGE))

    def test_gate_3_aces_and_kings_are_never_folded_to_one_re_raise_and_pairs_keep_their_order(self):
        # Kings were folded 20 times in the map of this spot: on the bubble and close to it, 25 to 45bb, raised
        # under the gun (61% against the re-raiser's range).  Never: where the all-in does not earn they call.
        for itm in (False, True):
            for left in (400, 200, 152, 100):
                for stack, open_to, villain, three in ((30, 2.2, "BB", 8.4), (45, 2.3, "BB", 8.7), (35, 2.2, "BTN", 6.6),
                                                       (45, 2.3, "BTN", 6.9)):
                    facing = f"hero raise {open_to}bb, {villain} raise {three}bb"
                    for hand in ("AA", "KK"):
                        adv = self.go(hand, stack, "UTG", facing, players=8, prizes=self.gate_prizes(left, itm, stack=stack))
                        self.assertIn(adv.action, ("ALL-IN", "CALL"), (itm, left, stack, villain, hand))
                        if adv.action == "CALL":
                            self.assertNotEqual(adv.confidence, "close")
                            self.assertLessEqual(self.shove_number(adv), 0.5)
        worst = self.go("KK", 45, "UTG", "hero raise 2.3bb, BB raise 8.7bb", players=8, prizes=self.gate_prizes(152, True))
        self.assertEqual(worst.action, "CALL")
        self.assertIn("aces and kings are never folded before the flop to one re-raise", " ".join(worst.why))
        self.assertLess(self.shove_number(worst), -1.0)                     # the all-in is no play there
        # against a re-raiser tagged nit after an early raise kings are behind even at the price (28% against
        # 34%): still no fold, but a close call without the plan to put the stack in, as it is with 60bb
        nit = ["unknown"] * 7 + ["nit"]
        for stack in (40, 60):
            adv = self.play([stack] * 8, 0, "KK", [(0, "raise", 2.3), (7, "raise", 8.7)], types=nit)
            self.assertEqual((adv.action, adv.confidence), ("CALL", "close"), stack)
            self.assertNotIn("the stack goes in", " ".join(adv.why))
        # within one spot no pair folds where a smaller pair plays
        pairs = ["AA", "KK", "QQ", "JJ", "TT", "99", "77", "22"]
        for hero, villain, open_to, three in ((0, 7, 2.3, 8.7), (3, 5, 2.3, 6.9), (6, 7, 3.0, 9.0)):
            for stack in (30, 45):
                for left in (None, 400, 152):
                    got = [self.play([stack] * 8, hero, hand, [(hero, "raise", open_to), (villain, "raise", three)],
                                     left=left).action for hand in pairs]
                    folded = [i for i, action in enumerate(got) if action == "FOLD"]
                    if folded:
                        self.assertEqual(folded, list(range(folded[0], len(pairs))), (hero, villain, stack, left, got))
                    self.assertNotIn(0, folded)
                    self.assertNotIn(1, folded)

    def test_gate_4_a_raise_and_a_re_raise_in_front_has_one_solution_and_a_number_to_believe(self):
        # Queens in the big blind with 20bb, under the gun raises to 2.2bb, the button re-raises to 6.6bb.  On
        # chips: ALL-IN [clear], "shove EV +12.89bb ... both fold 0%"; 400 left of 1,000: FOLD, -0.57bb.  The
        # solver had two solutions (preflop._cold_allin says why).  One spot, one answer, near one number.
        facing = "UTG raise 2.2bb, BTN raise 6.6bb"
        chips = self.go("QQ", 20, "BB", facing, players=8)
        far = self.go("QQ", 20, "BB", facing, players=8, prizes=self.gate_prizes(400, True, stack=20))
        self.assertEqual((chips.action, far.action), ("FOLD", "FOLD"))
        self.assertLess(abs(self.shove_number(chips)), 1.0)
        self.assertLess(abs(self.shove_number(chips) - self.shove_number(far)), 1.0)
        self.assertEqual(chips.confidence, "close")                         # ... and it says how thin the fold is
        # Against an early raise these hands are no favourite when called (45% or less against the re-raiser's
        # range), so their all-in cannot earn more than the dead money it wins when both fold: no number above
        # it, at any depth, on chips or with prizes.
        for raiser, reraiser in ((0, 5), (4, 5)):
            for left in (None, 400):
                last = {}
                for stack in (12, 16, 20, 25, 30):
                    acts = [(raiser, "raise", 2.2), (reraiser, "raise", 6.6)]
                    for hand in ("JJ", "QQ", "AKs", "AKo"):
                        adv = self.play([stack] * 8, 7, hand, acts, left=left)
                        number = self.shove_number(adv)
                        if raiser == 0:
                            self.assertLess(number, 2.2 + 6.6 + 0.5 + 1.0, (left, stack, hand))
                        if abs(number - 0.5) > 0.011:                       # (the printed number is rounded)
                            self.assertEqual(adv.action == "ALL-IN", number > 0.5, (raiser, left, stack, hand, number))
                        # stack to stack the number moves by a few big blinds at most (it fell from +12.89bb
                        # with 20bb to +2.92bb with 22bb and -0.32bb with 25bb)
                        if hand in last:
                            self.assertLess(abs(number - last[hand]), 4.0, (raiser, left, stack, hand))
                        last[hand] = number
                    for hand in ("AA", "KK"):
                        self.assertEqual(self.play([stack] * 8, 7, hand, acts, left=left).action, "ALL-IN", (stack, hand))
        # against an early raise and a re-raise the short column of the sheet is the top only; against a late
        # raise JJ+ and ace-king still play (the 3-bettor's range is twice as wide)
        early = {hand: self.play([20] * 8, 7, hand, [(0, "raise", 2.2), (5, "raise", 6.6)]).action for hand in ("JJ", "QQ", "AKs")}
        late = {hand: self.play([20] * 8, 7, hand, [(4, "raise", 2.2), (5, "raise", 6.6)]).action for hand in ("JJ", "QQ", "AKo")}
        self.assertEqual(early, {"JJ": "FOLD", "QQ": "FOLD", "AKs": "ALL-IN"})
        self.assertEqual(late, {"JJ": "ALL-IN", "QQ": "ALL-IN", "AKo": "ALL-IN"})
        # The bubble is not played looser for it.  Solved against JJ+ and ace-king alone, both players fold
        # kings there and a 60bb all-in with ace-king showed +3.18bb; the lowest of the three pricings counts.
        for hand, pos, facing, itm in (("AKs", "BTN", "HJ raise 2.3bb, CO raise 6.9bb", False),
                                       ("AKo", "BB", "LJ raise 2.3bb, BTN raise 6.9bb", True)):
            adv = self.go(hand, 60, pos, facing, players=6, prizes=self.gate_prizes(152, itm, players=6, stack=60))
            self.assertEqual(adv.action, "FOLD", (hand, adv.numbers))
            self.assertLess(self.shove_number(adv), 0.5, hand)

    def test_gate_5_these_answers_take_well_under_a_second(self):
        import time
        spots = (("QQ", 45, "HJ", "hero raise 2.3bb, BB raise 8.7bb"), ("QQ", 20, "BB", "UTG raise 2.2bb, BTN raise 6.6bb"),
                 ("KK", 40, "BTN", "UTG raise 2.2bb, HJ raise 6.6bb"))
        for hand, stack, pos, facing in spots:
            took = []
            for _ in range(3):
                start = time.perf_counter()
                self.go(hand, stack, pos, facing, players=8, prizes=self.gate_prizes(400, True, stack=stack))
                took.append(time.perf_counter() - start)
            self.assertLess(min(took), 1.0, (hand, facing, took))


class Postflop(unittest.TestCase):
    def go(self, hero, board, pot, to_call=0.0, stack=40.0, vs="call:BB", line="", **kw):
        w, label = range_from_spec(vs, 9, "unknown", 3)
        v = Villain(w, kw.pop("ptype", "unknown"), parse_line(line), label)
        return advise_postflop(PostflopSpot(tuple(parse_cards(hero)), parse_cards(board), pot,
                                            to_call, stack, None, [v], **kw))

    def test_value_and_air(self):
        self.assertTrue(self.go("AhKd", "Ks7d2c", 5.5, hero_pfr=True).action.startswith("BET"))
        self.assertEqual(self.go("AhQd", "9s8s7d", 5.5, hero_pfr=True).action, "CHECK")
        self.assertNotEqual(self.go("7h7d", "Ks7s2c", 6, to_call=2).action, "FOLD")

    def test_river_overbet_with_air(self):
        adv = self.go("QhJh", "Ks7d2c5h9s", 30, to_call=20, stack=25, line="flop=call turn=call")
        self.assertEqual(adv.action, "FOLD")

    def test_nuts_never_fold(self):
        adv = self.go("AhKh", "Qh7h2c5h9s", 30, to_call=20, stack=25, line="flop=call turn=call")
        self.assertNotEqual(adv.action, "FOLD")

    def test_line_parser(self):
        self.assertEqual(parse_line("flop=call turn=bet66"), [("flop", "call", None), ("turn", "bet", 0.66)])
        with self.assertRaises(ValueError):
            parse_line("flop=dance")

    @staticmethod
    def spot(hero, board, pot, to_call, stack, specs, vstack=None, in_position=False, **kw):
        villains = []
        for spec in specs:
            w, label = range_from_spec(spec, 9, "unknown", 0)
            villains.append(Villain(w, "unknown", [], label))
        return PostflopSpot(tuple(parse_cards(hero)), parse_cards(board), pot, to_call, stack, vstack, villains,
                            in_position, False, **kw)

    def test_post_3_a_cheap_call_is_never_folded_with_the_pot_odds(self):
        # the reviewer's hands: the last 4bb into a pot of 86bb, and the last 0.7bb into 70bb
        adv = advise_postflop(self.spot("8d7s", "8cJd5c", 18045, 826, 826, ["flat:BTN", "limp:UTG", "flat:BTN", "3bet"],
                                        vstack=0.0, bb=200, risk_premium=0.004))
        self.assertEqual(adv.action, "CALL")
        adv = advise_postflop(self.spot("7d8s", "Js8c5c", 42050, 425, 425, ["open:UTG", "flat:BTN"], vstack=0.0, bb=600,
                                        risk_premium=0.02))
        self.assertEqual(adv.action, "CALL")
        # the points added to the pot odds shrink with the price: none up to a tenth of the pot, all from half
        seen = []
        for hero, board in (("7d8s", "Js8c5c"), ("Ah2h", "Js8c5c"), ("KcQd", "As7h4d"), ("9h3h", "Kd9s4c2h"),
                            ("QhTd", "Qs8d3c7h2s")):
            for rp in (0.0, 0.12):
                last = None
                for share in (0.03, 0.06, 0.10, 0.15, 0.25, 0.35, 0.5, 0.75, 1.0):
                    pot = 40.0
                    call = pot * share
                    adv = advise_postflop(self.spot(hero, board, pot + call, call, call, ["open:UTG", "flat:BTN"],
                                                    risk_premium=rp))
                    d = adv.data
                    key = (hero, board, rp, share)
                    self.assertAlmostEqual(d["call_share"], share, places=6)
                    added = d["safety_pts"] + d["icm_pts"]
                    self.assertAlmostEqual(d["need_total"], d["pot_odds"] + added, places=6, msg=key)   # no draws here
                    if share <= 0.10:
                        self.assertEqual(added, 0.0, key)
                        if d["equity"] >= d["pot_odds"]:
                            self.assertNotEqual(adv.action, "FOLD", key)
                    if last is not None:
                        self.assertGreaterEqual(added, last - 1e-9, key)          # a dearer call, never fewer points
                    last = added
                    if share >= 0.5 and board != "Qs8d3c7h2s":
                        # out of position (2) and several players (3), in full; the river has its own points
                        self.assertAlmostEqual(d["safety_pts"], 0.05, places=6, msg=key)
                    if rp == 0.0:
                        self.assertEqual(d["icm_pts"], 0.0)
                        self.assertFalse(any("ICM" in text for text in adv.why), (key, adv.why))   # nothing to blame
                    if adv.action == "FOLD" and d["equity"] >= d["pot_odds"]:
                        seen.append(key)
                        self.assertGreater(added, 0.0, key)
                        self.assertEqual(len(adv.why), 2, (key, adv.why))         # the fold says which points did it
                        self.assertEqual("ICM" in adv.why[1], d["icm_pts"] > 0, (key, adv.why))
        self.assertTrue(any(k[2] == 0.0 for k in seen) and any(k[2] > 0 for k in seen), seen)

    def test_post_9_a_flop_bet_from_a_caller_is_not_a_continuation_bet(self):
        def facing(hero, board, size, pfr):
            w, label = range_from_spec("limp:SB", 3, "unknown", 0)
            v = Villain(w, "unknown", [], label, pfr)
            return advise_postflop(PostflopSpot(tuple(parse_cards(hero)), parse_cards(board), 2.0 + 2.0 * size,
                                                2.0 * size, 30.0, 30.0, [v], True, False))

        self.assertIsNone(Villain([1.0] * 169).pfr)                              # not known: as before
        for hero, board in (("QhTd", "As7h4d"), ("KcJd", "As7h4d"), ("Kh2d", "Tc6d2s")):
            unknown, raiser, caller = (facing(hero, board, 1.0, pfr).data["equity"] for pfr in (None, True, False))
            self.assertEqual(unknown, raiser, (hero, board))
            # the bet of a player who only called before the flop holds less air
            self.assertLess(caller, unknown - 0.01, (hero, board))
        # queen high, no pair, no draw, against a pot-sized bet from the small blind who only called: fold
        self.assertEqual(facing("QhTd", "As7h4d", 1.0, False).action, "FOLD")
        # made hands still continue
        for hero in ("Ad5c", "7s7d"):
            self.assertNotEqual(facing(hero, "As7h4d", 1.0, False).action, "FOLD", hero)

    # ---- L5: three oddities with nothing to call -------------------------------------------------

    @staticmethod
    def first_to_bet(hero, board, pot, stack, ranges, pfr=False, in_position=True, bb=1.0):
        villains = []
        for spec in ranges:
            w, label = range_from_spec(spec, 9, "unknown", 3)
            villains.append(Villain(w, "unknown", [], label))
        return advise_postflop(PostflopSpot(tuple(parse_cards(hero)), parse_cards(board), pot, 0.0, stack, None,
                                            villains, in_position, pfr, bb=bb))

    def test_a_strong_draw_against_several_players_is_a_bet_not_nothing_strong(self):
        # the review's own table: QhJh on Th9h2c against two players was a check "multi-way with nothing strong"
        # beside "21 outs, 54% equity".  The playbook bets real hands and strong draws multi-way.
        two = ["open:UTG", "call:BB"]
        adv = self.first_to_bet("QhJh", "Th9h2c", 8, 31, two)
        self.assertTrue(adv.action.startswith("BET ") and adv.action.endswith("(semi-bluff)"), adv.action)
        self.assertIn("a strong draw (~21 outs", adv.why[0])
        self.assertTrue(self.first_to_bet("Ah5h", "Th9h2c", 8, 31, two).action.endswith("(semi-bluff)"))   # 12 outs
        # out of position it is a check, and the check does not call the draw "nothing"
        adv = self.first_to_bet("QhJh", "Th9h2c", 8, 31, two, in_position=False)
        self.assertEqual(adv.action, "CHECK")
        self.assertIn("a draw (~21 outs) against several players", adv.why[0])
        # a draw of 8 to 11 outs checks, with the same words; no draw at all is still "nothing strong"
        adv = self.first_to_bet("8c7d", "Th9h2c", 8, 31, two)
        self.assertEqual(adv.action, "CHECK")
        self.assertIn("a draw (~8 outs) against several players", adv.why[0])
        self.assertIn("nothing strong", self.first_to_bet("AcQd", "Th9h2c", 8, 31, two).why[0])
        # under ICM pressure nothing is bet as a bluff into two players
        spot = PostflopSpot(tuple(parse_cards("QhJh")), parse_cards("Th9h2c"), 8, 0.0, 31, None,
                            [Villain(range_from_spec(x, 9, "unknown", 3)[0]) for x in two], True, False, risk_premium=0.08)
        self.assertEqual(advise_postflop(spot).action, "CHECK")

    def test_l5_a_strong_made_hand_bets_for_value_or_checks_to_call(self):
        sets = "KK, TT, 77, 44, AKs, KTs, QJs, J9s, 98s"
        # the review's hand: aces with the nut flush draw on 4sTsKh7s against two players was a check
        # "multi-way with nothing strong".  It is a bet for value ...
        adv = self.first_to_bet("AhAs", "4sTsKh7s", 20, 60, ["flat:BTN", "call:BB"])
        self.assertTrue(adv.action.startswith("BET "), adv.action)
        self.assertNotIn("semi-bluff", adv.action)
        self.assertIn("bet for value", adv.why[0])
        self.assertTrue(0.55 <= adv.data["equity"] < 0.72, adv.data)             # under the plain value bet's 72%
        # ... and against two ranges it is behind, a check that says why and what comes next
        adv = self.first_to_bet("AhAs", "4sTsKh7s", 20, 60, [sets, "KK, TT, 77, KQs, AKs"])
        self.assertEqual(adv.action, "CHECK")
        self.assertRegex(adv.why[0], r"^a good hand, but with \d+% against these ranges it is not far enough ahead")
        self.assertLess(adv.data["equity"], 0.40)
        self.assertIn("call one reasonable bet", adv.why[0])
        # every hand of top pair with a strong kicker or better, whatever the ranges: never "nothing", never
        # a bluff's label, and a check always says it is a check to call
        seen = set()
        for hero, board in (("AhAs", "4sTsKh7s"), ("QhQd", "JsTs9s"), ("AhKh", "Ks7h2h"), ("AhKd", "Ks7h2h"),
                            ("JhJd", "9s5d2c"), ("KhTd", "KsTs4s7s"), ("AhKd", "Ks7d2c"), ("9h9d", "8s7s2c5d6h")):
            for ranges in (["call:BB"], [sets], ["flat:BTN", "call:BB"], [sets, "TT+, 99, 55, AKs"]):
                for pfr in (False, True):
                    for in_position in (False, True):
                        adv = self.first_to_bet(hero, board, 12, 60, ranges, pfr, in_position)
                        if adv.data["strength"] < 5:
                            continue
                        key = (hero, board, ranges, pfr, in_position, adv.action)
                        text = " ".join(adv.why)
                        self.assertNotIn("nothing strong", text, key)
                        self.assertNotIn("no value and no good bluff", text, key)
                        self.assertNotIn("semi-bluff", adv.action, key)
                        self.assertNotIn("c-bet", adv.action, key)
                        self.assertFalse(any("give up on the turn" in w for w in adv.warnings), key)
                        if adv.action == "CHECK":
                            self.assertIn("call one reasonable bet", text, key)
                        seen.add(adv.action.split()[0])
        self.assertEqual(seen, {"BET", "CHECK"})
        # weaker hands keep their lines: a draw is a semi-bluff, air on a dry board a continuation bet
        self.assertIn("(semi-bluff)", self.first_to_bet("QhJh", "Th9h2c", 5.5, 40, ["call:BB"], pfr=True).action)
        self.assertIn("(c-bet)", self.first_to_bet("AhQd", "Ks7d2c", 5.5, 40, ["call:BB"], pfr=True).action)
        self.assertIn("nothing strong", self.first_to_bet("QhJd", "Ts7s4d", 12, 60, ["flat:BTN", "call:BB"]).why[0])

    def test_l5_a_value_bet_of_two_thirds_of_the_stack_is_the_all_in(self):
        # the review's hand: KJ on 3c4hKs3d with 7,313 behind was "BET 6,374", 87% of the stack
        adv = self.first_to_bet("JdKc", "3c4hKs3d", 12748, 7313, ["call:BB"], bb=600)
        self.assertEqual(adv.action, "BET ALL-IN")
        self.assertFalse(any("fold to a raise" in w for w in adv.warnings), adv.warnings)   # nothing is left to fold
        deep = self.first_to_bet("JdKc", "3c4hKs3d", 12748, 40000, ["call:BB"], bb=600)
        self.assertEqual(deep.action, "BET 6,374 (10.6bb, 50% pot)")
        self.assertTrue(any("fold to a raise unless" in w for w in deep.warnings))
        # no sized bet with nothing to call is two thirds of what is behind, or more
        for stack in (3, 4, 5, 6, 8, 10, 13, 20):
            for hero, board in (("JdKc", "3c4hKs3d"), ("AhKd", "Ks7d2c"), ("AhAs", "4sTsKh7s"), ("Qh8s", "TdQc2s"),
                                ("7h7d", "Ks7s2c"), ("AhKh", "Ks7h2h")):
                for pfr in (False, True):
                    adv = self.first_to_bet(hero, board, 10, stack, ["call:BB"], pfr)
                    size = re.match(r"BET ([\d.]+)bb", adv.action)
                    if size and "semi-bluff" not in adv.action and "c-bet" not in adv.action:
                        self.assertLess(float(size.group(1)), 2 / 3 * stack + 0.051, (hero, board, stack, pfr, adv.action))

    def test_l5_a_bet_with_top_pair_or_better_is_not_called_a_c_bet(self):
        # the review's hand: Q8 on TdQc2s as the raiser.  Against a range it is not far ahead of, the small
        # bet was labelled "c-bet", "whatever you hold", with "give up on the turn"
        tight = "QQ, TT, 22, AQs, KQs, QJs, QTs, AQo, KQo, JJ, 99"
        for ranges in (["call:BB"], [tight]):
            adv = self.first_to_bet("Qh8s", "TdQc2s", 5.5, 40, ranges, pfr=True)
            self.assertEqual(adv.action, "BET 1.8bb (33% pot)", ranges)
            self.assertIn("top pair", adv.why[0])
            self.assertIn("fold to a raise unless this player is aggressive", adv.warnings)
            self.assertFalse(any("give up on the turn" in w for w in adv.warnings))
        strong = self.first_to_bet("AhKd", "Ks7d2c", 5.5, 40, ["KK, 77, 22, AKs, AKo, KQs"], pfr=True)
        self.assertEqual(strong.action, "BET 1.8bb (33% pot)")
        self.assertIn("for value and protection", strong.why[0])
        # with less than top pair it is still the continuation bet
        for hero in ("AhQd", "9h9d", "7h6h"):
            adv = self.first_to_bet(hero, "Ks8d2c", 5.5, 40, ["call:BB"], pfr=True)
            self.assertTrue(adv.action.endswith("(c-bet)"), (hero, adv.action))


class StateAndCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = S.STATE_PATH
        S.STATE_PATH = os.path.join(self.tmp.name, "current.json")

    def tearDown(self):
        S.STATE_PATH = self.old
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    SNAP = ('{"blinds":[300,600,75],"button":3,"hero":5,"remaining":96,"seats":{"1":["Bob",21000],'
            '"2":["Ann",9500],"3":["Carl",48000],"4":["Dee",15500],"5":["HERO",12400],'
            '"6":["Eve",33000],"7":["Fox",6200],"8":["Gus",27000],"9":["Hal",18000]}}')

    def test_positions(self):
        st = S.blank_state()
        S.apply_snapshot(st, {"blinds": [100, 200], "button": 3,
                              "seats": {str(i): [f"P{i}", 10000] for i in range(1, 10)}})
        pos = S.positions(st)
        self.assertEqual(pos[3], "BTN")
        self.assertEqual(pos[4], "SB")
        self.assertEqual(pos[5], "BB")
        self.assertEqual(pos[6], "UTG")
        self.assertEqual(pos[2], "CO")
        self.assertEqual(S.action_order(st)[0], 6)
        # heads-up: the button posts the small blind and acts first
        st2 = S.blank_state()
        S.apply_snapshot(st2, {"blinds": [100, 200], "button": 7, "seats": {"2": ["A", 5000], "7": ["B", 5000]}})
        self.assertEqual(S.action_order(st2), [7, 2])
        # three-handed
        st3 = S.blank_state()
        S.apply_snapshot(st3, {"blinds": [100, 200], "button": 1,
                               "seats": {"1": ["A", 1], "4": ["B", 1], "8": ["C", 1]}})
        self.assertEqual([S.positions(st3)[s] for s in (1, 4, 8)], ["BTN", "SB", "BB"])

    def test_full_session(self):
        code, out, _ = self.run_cli("new", "--name", "Test", "--buyin", "11", "--entrants", "500",
                                    "--paid", "75", "--start-stack", "10000")
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli("sync", self.SNAP)
        self.assertEqual(code, 0)
        self.assertIn("NEAR THE BUBBLE", out)
        self.assertIn("HERO", out)
        code, out, _ = self.run_cli("advise", "--hand", "AA", "--facing", "Ann allin")
        self.assertEqual(code, 0)
        self.assertNotIn(">>> FOLD", out)
        code, out, _ = self.run_cli("bust", "Fox")
        self.assertEqual(code, 0)
        st = S.load()
        self.assertEqual(st["tournament"]["remaining"], 95)
        self.assertNotIn("7", S.seats(st))
        code, out, _ = self.run_cli("undo")
        self.assertEqual(S.load()["tournament"]["remaining"], 96)
        self.assertIn("7", S.seats(S.load()))
        code, out, _ = self.run_cli("stack", "Carl", "52k", "hero", "13000")
        self.assertEqual(S.seats(S.load())["3"]["stack"], 52000)
        self.assertEqual(S.hero_stack(S.load()), 13000)
        code, out, _ = self.run_cli("type", "Carl", "lag")
        self.assertEqual(S.seats(S.load())["3"]["type"], "lag")
        code, out, _ = self.run_cli("next")
        self.assertEqual(S.load()["table"]["button"], 4)
        code, out, _ = self.run_cli("icm")
        self.assertIn("risk premium", out)
        code, out, _ = self.run_cli("advise", "--hand", "AhKd", "--board", "Ks7d2c", "--pot", "4500",
                                    "--to-call", "1500", "--vs", "open:UTG", "--villain", "Gus")
        self.assertEqual(code, 0, out)
        self.assertIn(">>>", out)
        code, _, err = self.run_cli("bust", "nobody")
        self.assertEqual(code, 2)
        self.assertIn("no player matches", err)

    def test_snapshot_diff(self):
        st = S.blank_state()
        S.apply_snapshot(st, {"blinds": [100, 200], "seats": {"1": ["A", 5000], "2": ["B", 7000], "3": ["C", 9000]}})
        ch = S.apply_snapshot(st, {"blinds": [150, 300], "seats": {"1": ["A", 6500], "2": None, "3": ["Zed", 4000]}})
        text = " | ".join(ch)
        self.assertIn("blinds now 150/300", text)
        self.assertIn("+1,500", text)
        self.assertIn("is OUT", text)
        self.assertIn("replaced by Zed", text)
        self.assertNotIn("2", S.seats(st))
        # a name misread by one character is the same player, notes kept
        S.seats(st)["1"]["notes"] = ["tight"]
        ch = S.apply_snapshot(st, {"seats": {"1": ["A", 6500]}})
        S.seats(st)["1"]["name"] = "Bob_l23"
        ch = S.apply_snapshot(st, {"seats": {"1": ["Bob_123", 6500]}})
        self.assertEqual(ch, [])
        self.assertEqual(S.seats(st)["1"]["notes"], ["tight"])
        # a complete snapshot drops everyone who is not listed
        ch = S.apply_snapshot(st, {"complete": True, "seats": {"3": ["Zed", 4100]}})
        self.assertEqual(list(S.seats(st)), ["3"])

    def test_quick_and_tools(self):
        code, out, _ = self.run_cli("quick", "--hand", "A8s", "--stack", "9", "--pos", "BTN")
        self.assertEqual(code, 0)
        self.assertIn(">>> ALL-IN", out)
        code, out, _ = self.run_cli("equity", "--hand", "AKo", "--vs", "QQ")
        self.assertIn("equity 43", out)
        code, out, _ = self.run_cli("chart", "push", "--pos", "SB", "--stack", "12")
        self.assertIn("Nash open-shove", out)
        code, out, _ = self.run_cli("range", "77+,", "AJs+", "--grid")
        self.assertIn("##", out)
        code, _, err = self.run_cli("quick", "--hand", "ZZ", "--stack", "9", "--pos", "BTN")
        self.assertEqual(code, 2)

    def test_fold_clock(self):
        st = S.blank_state()
        S.apply_snapshot(st, {"blinds": [500, 1000], "bb_ante": 1000, "button": 1, "hero": 2,
                              "entrants": 300, "paid": 45, "remaining": 60, "avg_stack": 50000,
                              "seats": {str(i): [f"P{i}", 40000] for i in range(1, 10)}})
        self.assertAlmostEqual(S.total_chips(st), 3_000_000)
        # 60 -> 50 players in ten minutes: one bust a minute, five to go
        st["history"] = [{"t": 0.0, "remaining": 60}, {"t": 600.0, "remaining": 50}]
        st["tournament"]["remaining"] = 50
        self.assertAlmostEqual(S.bust_rate(st), 1.0)
        S.seats(st)["2"]["stack"] = 30000          # 12 orbits of 9 hands: plenty of time
        self.assertEqual(S.fold_clock(st)["verdict"], "safe")
        S.seats(st)["2"]["stack"] = 1000           # 0.4 orbits (3 min) against a 6.5 min bubble
        self.assertEqual(S.fold_clock(st)["verdict"], "short")
        # the average follows the chips in play, not a stale lobby number
        self.assertAlmostEqual(S.avg_stack(st), 60000)

    def test_partial_payout_list(self):
        st = S.blank_state()
        S.apply_snapshot(st, {"entrants": 100, "paid": 15, "payouts": [300, 200, 120]})
        self.assertEqual(S.paid_places(st), 15)
        self.assertEqual(len(S.payouts(st)), 15)
        self.assertEqual(S.payouts(st)[-1], 120)

    def test_stage_and_prizes(self):
        st = S.blank_state()
        S.apply_snapshot(st, {"blinds": [100, 200], "button": 1, "hero": 2, "entrants": 200, "paid": 30,
                              "start_stack": 5000, "remaining": 31,
                              "seats": {str(i): [f"P{i}", 30000] for i in range(1, 7)}})
        self.assertEqual(S.stage(st)["code"], "bubble")
        self.assertGreater(S.build_prizes(st).itm_bonus, 0)
        self.assertTrue(S.build_prizes(st, "chips").chip_ev)
        S.apply_snapshot(st, {"remaining": 28})
        self.assertEqual(S.stage(st)["code"], "itm")
        self.assertEqual(S.build_prizes(st).itm_bonus, 0)   # the bonus is only for getting there
        self.assertEqual(rfi_range(2)[HAND_INDEX["AA"]], 1.0)

    def test_g_e4_a_decision_in_a_very_large_field_is_answered_while_the_clock_runs(self):
        # Found at the gate: `quick --hand A8s --stack 9 --pos BTN` took 8 seconds with 60,000 entrants (9,300
        # left, 9,000 paid) and 34 seconds with 150,000 (22,500 left, 22,000 paid): the integral of the prize
        # model grows with the paid places that can still be reached.  The table app had its closed form for
        # that (advice.thinned_prizes); quick, advise and icm now use it under the same condition.
        import time
        from poker_coach import cli
        from poker_coach.app import advice as A
        self.assertEqual(cli.PRIZE_PLACES, A.PRIZE_PLACES)
        for entrants, paid, left, table in ((500, 75, 78, 9), (5000, 750, 800, 9), (8000, 1200, 1300, 9),
                                            (8000, 1200, 900, 9), (150000, 22000, 22500, 7), (150000, 22000, 600, 9)):
            pays = default_payouts(entrants, paid)
            prizes = Prizes(pays, left - table, 20.0, itm_bonus=pays[-1], label="x")
            mine, theirs = cli._large_field(prizes, table), A.thinned_prizes(prizes, table)
            where = (entrants, paid, left)
            self.assertEqual(mine.large, theirs.large, where)              # the app's condition, case by case
            self.assertEqual(mine.large, min(paid, left) > 1000, where)    # more than 1,000 paid places to reach
            self.assertEqual((mine.raw_payouts, mine.field_n, mine.field_stack, mine.itm_bonus, mine.label),
                             (prizes.raw_payouts, prizes.field_n, prizes.field_stack, prizes.itm_bonus, "x"), where)
            self.assertIs(cli._large_field(mine, table), mine)
            others = cli._field_prizes(mine)                               # the opponents: the same model, no bonus
            self.assertEqual((others.large, others.itm_bonus, others.raw_payouts), (mine.large, 0.0, pays), where)
        self.assertTrue(cli._large_field(Prizes(), 9).chip_ev)
        self.assertTrue(cli._field_prizes(Prizes()).chip_ev)

        def timed(*args):
            start = time.time()
            code, out, err = self.run_cli(*args)
            self.assertEqual(code, 0, err)
            self.assertLess(time.time() - start, 5.0, args)                # (a third of a second; it was 34)
            return out

        big = ("--remaining", "22500", "--paid", "22000", "--entrants", "150000")
        out = timed("quick", "--hand", "A8s", "--stack", "9", "--pos", "BTN", *big)
        self.assertIn(">>> ALL-IN   [clear]", out)
        self.assertIn("ICM (22500 left, 22000 paid, ITM-first)", out)
        # ... the answer did not move: these are the lines the integral printed for the four fields of the gate
        for field, lines in (
                (("--remaining", "1300", "--paid", "1200", "--entrants", "8000"),
                 ("16% risk premium against SB", "shove EV +0.64bb vs folding", "equilibrium shoves 34% of hands here",
                  "everyone folds 73%; when called you have 42%")),
                (("--remaining", "3100", "--paid", "3000", "--entrants", "20000"),
                 ("16% risk premium against SB", "shove EV +0.61bb vs folding", "equilibrium shoves 32% of hands here",
                  "everyone folds 74%; when called you have 41%")),
                (big, ("15% risk premium against SB", "shove EV +0.66bb vs folding", "equilibrium shoves 32% of hands here",
                       "everyone folds 73%; when called you have 42%"))):
            out = timed("quick", "--hand", "A8s", "--stack", "9", "--pos", "BTN", *field)
            for line in lines:
                self.assertIn(line, out, field)
        # ... and against the integral itself, asked here for the smallest of them: the same answer, line for line
        hand, cards = parse_hand("A8s")
        pays = default_payouts(8000, 1200)
        exact = Prizes(pays, 1300 - 9, 9.0, itm_bonus=pays[-1], label="ICM (1300 left, 1200 paid, ITM-first)")
        spot = quick_spot(hand, cards, 9.0, 9, "BTN", "", None, exact, True, {"label": "100 from the money", "to_money": 100})
        spot.field_prizes = Prizes(pays, 1300 - 9, 9.0)
        self.assertFalse(exact.large)
        out = timed("quick", "--hand", "A8s", "--stack", "9", "--pos", "BTN", "--remaining", "1300", "--paid", "1200",
                    "--entrants", "8000")
        self.assertEqual(out.split("ctx:")[0].strip(), advise(spot).render().strip())
        # a field under the cap is still the integral: nothing changes for it
        self.assertIn("shove EV +0.52bb vs folding (ICM (78 left, 75 paid, ITM-first))",
                      timed("quick", "--hand", "A8s", "--stack", "9", "--pos", "BTN", "--remaining", "78", "--paid", "75",
                            "--entrants", "500"))
        # the tracked table: advise (before and after the flop) and icm
        self.run_cli("new", "--name", "big", "--buyin", "11", "--entrants", "150000", "--paid", "22000", "--start-stack", "10000")
        self.run_cli("sync", '{"blinds":[300,600,75],"button":1,"hero":5,"remaining":22500,"seats":{"1":["Bob",21000],'
                             '"2":["Ann",9500],"3":["Carl",48000],"4":["Gus",30000],"5":["HERO",5400],"6":["Fox",8000],'
                             '"7":["Dee",15000]}}')
        self.assertIn(">>> ALL-IN", timed("advise", "--hand", "A8s"))
        self.assertIn(">>> FOLD", timed("advise", "--hand", "KTs", "--facing", "Fox allin"))
        self.assertIn("ICM risk premium", timed("advise", "--hand", "AhKd", "--board", "Ks7d2c", "--pot", "4500", "--to-call",
                                                "1500", "--vs", "open:UTG", "--villain", "Gus", "--oop"))
        table = timed("icm")
        self.assertIn("ICM (22500 left, 22000 paid, ITM-first)", table)
        self.assertEqual(len(re.findall(r"bubble factor \d", table)), 6)       # hero's premium against each of the six


if __name__ == "__main__":
    unittest.main()


class Fuzz(unittest.TestCase):
    """Random tables and action sequences must always produce an answer."""

    def test_random_preflop_spots(self):
        from poker_coach.preflop import Spot, parse_actions, pos_to_index
        from poker_coach.ranges import PLAYER_TYPES, position_name

        rng = random.Random(11)
        pays = default_payouts(500)
        verbs = ["limp", "call", "raise 2.2bb", "raise 900", "raise 3x", "allin", "fold"]
        for _ in range(70):
            n = rng.randint(2, 9)
            stacks = [200.0 * rng.choice([1.2, 3, 6, 9, 12, 16, 22, 30, 50, 120]) for _ in range(n)]
            ante, bb_ante = rng.choice([(0, 0), (25, 0), (0, 200)])
            setup = HandSetup(stacks, 100, 200, ante, bb_ante)
            hero = rng.randrange(n)
            names = [position_name(n - 1 - i, n) for i in range(n)]
            rem = rng.choice([n, len(pays) + 2, 300])
            prizes = rng.choice([Prizes(), Prizes(pays, max(0, rem - n), sum(stacks) / n,
                                                  itm_bonus=pays[-1] if rem > len(pays) else 0.0)])
            spot = Spot(setup=setup, hero=hero, hand=rng.randrange(169), names=list(names),
                        types=[rng.choice(list(PLAYER_TYPES)) for _ in range(n)],
                        away=[rng.random() < 0.1 and i != hero for i in range(n)],
                        prizes=prizes, field_prizes=Prizes(prizes.raw_payouts, prizes.field_n, prizes.field_stack))
            who = sorted(rng.sample(range(n), min(n, rng.randint(0, 3))))
            if rng.random() < 0.3:
                who = [hero] + [i for i in who if i > hero]
            facing = ", ".join(("hero" if i == hero else names[i]) + " " +
                               ("raise 2.2bb" if i == hero else rng.choice(verbs)) for i in who)
            spot.acts = parse_actions(facing, setup, hero, lambda nm: pos_to_index(nm, n), chips=True)
            adv = advise(spot)
            self.assertTrue(adv.action and adv.render(), facing)

    def test_random_postflop_spots(self):
        rng = random.Random(12)
        specs = ["open:CO", "open:UTG", "call:BB", "flat:BTN", "3bet", "limp", "35%", "any", "77+, AJs+"]
        moves = ["check", "call", "bet", "bet33", "bet150", "raise", "shove"]
        for _ in range(70):
            deck = list(range(52))
            rng.shuffle(deck)
            board = deck[2:2 + rng.choice([3, 4, 5])]
            streets = ["flop", "turn", "river"][:len(board) - 2]
            villains = []
            for _ in range(rng.choice([1, 1, 2, 3])):
                w, label = range_from_spec(rng.choice(specs), rng.randint(2, 9), "unknown", rng.choice([None, 0, 2, 5]))
                line = " ".join(f"{s}={rng.choice(moves)}" for s in streets if rng.random() < 0.6)
                villains.append(Villain(w, rng.choice(["unknown", "nit", "station", "maniac"]), parse_line(line), label))
            pot = rng.uniform(3, 60)
            to_call = rng.choice([0.0, pot * rng.uniform(0.1, 0.6)])
            spot = PostflopSpot((deck[0], deck[1]), board, pot, to_call, rng.uniform(0.5, 150),
                                rng.choice([None, 0.0, 40.0]), villains, rng.random() < 0.5,
                                rng.random() < 0.5, risk_premium=rng.choice([0.0, 0.1, 0.2]), iters=1000)
            adv = advise_postflop(spot)
            self.assertTrue(adv.action and adv.render())


class AllInOrFold(unittest.TestCase):
    """The solved All-In or Fold tables (poker_coach/data/aof.json)."""

    def setUp(self):
        from poker_coach import aof
        self.A = aof

    def pct(self, family, n, hero, mask, stack):
        weights, ev, _ = self.A.node_range(family, n, hero, mask, stack)
        solid = [1.0 if e > 0 else 0.0 for e in ev]
        return range_pct(solid)

    def test_premiums_and_trash(self):
        A = self.A
        for family in ("cash", "chips"):
            for n in (2, 3, 4):
                for stack in A.stack_grid(family, n):
                    for hero, mask in A.decision_points(n):
                        ans = A.decide(HAND_INDEX["AA"], n, hero, mask, [stack] * n, family)
                        self.assertEqual(ans.action, "ALL-IN", (family, n, stack, hero, mask))
        self.assertEqual(A.decide(HAND_INDEX["72o"], 4, 0).action, "FOLD")
        self.assertEqual(A.decide(HAND_INDEX["32o"], 4, 1, 1).action, "FOLD")
        self.assertEqual(A.decide(HAND_INDEX["AKs"], 4, 3, 0b111).action, "ALL-IN")

    def test_shape_of_the_ranges(self):
        co, btn, sb = (self.pct("cash", 4, k, 0, 8) for k in (0, 1, 2))
        self.assertLess(co, btn)
        self.assertLess(btn, sb)
        self.assertTrue(20 < co < 34, co)
        self.assertTrue(50 < sb < 70, sb)
        # calling an all-in needs a far better hand than opening
        self.assertLess(self.pct("cash", 4, 1, 1, 8), btn / 2)
        # facing two all-ins is tighter still
        self.assertLess(self.pct("cash", 4, 2, 0b11, 8), self.pct("cash", 4, 2, 0b01, 8))
        # shorter stacks shove wider
        self.assertGreater(self.pct("cash", 4, 2, 0, 4), sb)

    def test_heads_up_matches_known_nash(self):
        self.assertAlmostEqual(self.pct("chips", 2, 0, 0, 10), 58.3, delta=3.0)
        self.assertAlmostEqual(self.pct("chips", 2, 1, 1, 10), 37.4, delta=3.0)

    def test_fee_is_the_only_leak(self):
        A = self.A
        self.assertAlmostEqual(sum(A.table_value("cash", 4, 8)), -0.1, delta=0.03)
        self.assertAlmostEqual(sum(A.table_value("chips", 4, 8)), 0.0, delta=0.03)
        # the blinds pay for the table
        val = A.table_value("cash", 4, 8)
        self.assertGreater(val[1], 0)
        self.assertLess(val[3], val[2])

    def test_effective_stack_and_interpolation(self):
        A = self.A
        self.assertEqual(A.effective_stack([8, 8, 8, 5.5], 2, 0), 5.5)      # SB first in, BB has 5.5
        self.assertEqual(A.effective_stack([6, 8, 8, 8], 3, 0b001), 6)      # BB facing a 6bb shove
        self.assertEqual(A.effective_stack([8, 7, 8, 3], 3, 0b011), 3)      # BB is the short one
        self.assertEqual(A.effective_stack([4, 8, 8, 8], 0, 0), 4)
        h = HAND_INDEX["K9o"]
        lo = A.decide(h, 4, 2, 0, [7] * 4).ev
        hi = A.decide(h, 4, 2, 0, [8] * 4).ev
        mid = A.decide(h, 4, 2, 0, [7.5] * 4).ev
        self.assertAlmostEqual(mid, (lo + hi) / 2, places=6)
        ans = A.decide(h, 4, 2, 0, [30] * 4)       # cash tables cap at 8bb
        self.assertEqual(ans.stack, 8)
        self.assertTrue(ans.notes)

    def test_seats_and_errors(self):
        A = self.A
        self.assertEqual(A.position_index("btn", 4), 1)
        self.assertEqual(A.position_index("BTN", 2), 0)
        self.assertEqual(A.parse_shovers("CO, BTN", 4, 3), 0b011)
        self.assertEqual(A.parse_shovers("", 4, 3), 0)
        with self.assertRaises(ValueError):
            A.parse_shovers("BB", 4, 1)            # the BB cannot have shoved before the button
        with self.assertRaises(ValueError):
            A.position_index("CO", 3)
        with self.assertRaises(ValueError):
            A.decide(HAND_INDEX["AA"], 4, 3, 0)    # folded to the big blind: no decision
        with self.assertRaises(ValueError):
            A.decide(HAND_INDEX["AA"], 6, 0, 0)

    def test_drills_and_cli(self):
        A = self.A
        rng = random.Random(5)
        for _ in range(40):
            sp = A.random_spot(rng)
            self.assertIn((sp.hero, sp.mask), A.decision_points(4))
            self.assertIn(sp.answer().action, ("ALL-IN", "FOLD"))
        for args in (["aof", "--hand", "A5s", "--pos", "BTN", "--shoved", "CO"],
                     ["aof", "--hand", "Q4o", "--pos", "SB", "--stacks", "SB=8,BB=5.5"],
                     ["aof", "--hand", "22", "--pos", "BB", "--shoved", "SB", "--players", "2",
                      "--stack", "15", "--mode", "tournament"],
                     ["aof-chart", "--pos", "SB", "--shoved", "CO"],
                     ["aof-sheet"],
                     ["aof-quiz", "--count", "4", "--seed", "1", "--print"]):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(args)
            self.assertEqual(code, 0, (args, err.getvalue()))
            self.assertTrue(out.getvalue().strip())
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["aof", "--hand", "AA", "--pos", "BB"])
        self.assertEqual(code, 2)


class AllInOrFoldLooseTables(unittest.TestCase):
    """Best-response ranges against opponents who call too wide."""

    def setUp(self):
        from poker_coach import aof
        self.A = aof

    def pct(self, family, hero, mask, stack=8.0, n=4):
        _, ev, _ = self.A.node_range(family, n, hero, mask, stack)
        return range_pct([1.0 if e > 0 else 0.0 for e in ev])

    def test_families(self):
        A = self.A
        self.assertEqual(A.family_for("cash", None), "cash")
        self.assertEqual(A.family_for("cash", "loose"), "cash-loose")
        self.assertEqual(A.family_for("cash", "very-loose"), "cash-vloose")
        self.assertEqual(A.family_for("tournament", "solid"), "chips")
        with self.assertRaises(ValueError):
            A.family_for("tournament", "loose")
        with self.assertRaises(ValueError):
            A.family_for("cash", "drunk")
        for fam in ("cash-loose", "cash-vloose"):
            for n in (2, 3, 4):
                self.assertEqual(A.stack_grid(fam, n), A.stack_grid("cash", n))

    def test_shove_tighter_when_nobody_folds(self):
        for hero in (0, 1, 2):
            solid = self.pct("cash", hero, 0)
            loose = self.pct("cash-loose", hero, 0)
            vloose = self.pct("cash-vloose", hero, 0)
            self.assertLess(loose, solid, hero)
            self.assertLess(vloose, solid, hero)
        # the monsters never change
        for fam in ("cash-loose", "cash-vloose"):
            for hero, mask in self.A.decision_points(4):
                self.assertEqual(self.A.decide(HAND_INDEX["AA"], 4, hero, mask, family=fam).action, "ALL-IN")

    def test_comparison_matrix(self):
        m = self.A.matrix()
        self.assertEqual(len(m), 9)
        self.assertAlmostEqual(m["solved|solid"]["bb100"], -2.5, delta=0.6)
        for fam in ("cash-loose", "cash-vloose"):
            # the tailored table does at least as well as the solved one against its own opponents
            self.assertGreaterEqual(m[f"{fam}|{fam}"]["bb100"], m[f"solved|{fam}"]["bb100"] - 0.3)
        # looser opponents are better opponents
        self.assertGreater(m["solved|cash-vloose"]["bb100"], m["solved|solid"]["bb100"])

    def test_drills_and_cli(self):
        A = self.A
        rng = random.Random(9)
        for _ in range(30):
            sp = A.random_spot(rng, family="cash-vloose")
            self.assertIn(sp.answer().action, ("ALL-IN", "FOLD"))
        for args, code in ((["aof", "--hand", "T5s", "--pos", "SB", "--vs", "loose"], 0),
                           (["aof-chart", "--pos", "SB", "--vs", "very-loose"], 0),
                           (["aof-sheet", "--vs", "loose"], 0),
                           (["aof-quiz", "--count", "3", "--seed", "2", "--print", "--vs", "very-loose"], 0),
                           (["aof-compare"], 0),
                           (["aof", "--hand", "T5s", "--pos", "SB", "--mode", "tournament", "--vs", "loose"], 2)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                got = main(args)
            self.assertEqual(got, code, (args, err.getvalue()))


class LateRegistration(unittest.TestCase):
    """The late-registration min-cash system (poker_coach/latereg.py)."""

    @classmethod
    def setUpClass(cls):
        from poker_coach import latereg
        cls.L = latereg
        cls.turbo = latereg.Blinds(1.20, 6.5)

    def test_blinds_and_fold_cost(self):
        L, bl = self.L, self.turbo
        self.assertEqual(bl.mult(0), 1.0)
        self.assertAlmostEqual(bl.mult(13), 1.2 ** 2, places=6)
        self.assertAlmostEqual(bl.hands_until(1.2 ** 3), 19.5, places=6)
        # one orbit costs the small blind, the big blind and the ante, whatever the seat
        flat = L.Blinds(1.0, 1000.0)
        for seat in range(8):
            self.assertAlmostEqual(L.fold_cost(8, flat, 8, seat), 2.5)
        self.assertAlmostEqual(L.fold_cost(8, flat, 8), 2.5)
        # rising blinds cost more, and a schedule is followed level by level
        self.assertGreater(L.fold_cost(40, bl, 8), L.fold_cost(40, flat, 8))
        sched = L.Blinds(1.2, 8.0, 0.0, (1000, 1200, 1500))
        self.assertAlmostEqual(sched.mult(8), 1.2)
        self.assertAlmostEqual(sched.mult(17), 1.5)
        self.assertAlmostEqual(sched.mult(24), 1.5 * 1.2)

    def test_waiting_costs_the_growth_of_the_average_stack(self):
        """Whatever the speed, a folder pays about 2.5/c chips per chip the average stack grows."""
        L = self.L
        for speed in ("hyper", "turbo", "regular", "slow"):
            sp = L.SPEEDS[speed]
            bl = L.Blinds(sp["growth"], sp["hands_per_level"])
            for remaining, paid, avg in ((300, 150, 30.0), (900, 300, 25.0), (2000, 1500, 40.0)):
                # without the bubble slowdown the rule is exact up to the size of a blind level
                hands = L.hands_to_bubble(remaining, paid, avg, bl, 8, bust=3.0, near=1.0, hfh=1.0)
                cost = L.fold_cost(hands, bl, 8)
                rule = 2.5 / 3.0 * avg * (remaining / paid - 1.0)
                self.assertLess(abs(cost / rule - 1.0), 0.22, (speed, remaining, paid, cost, rule))
                # with it, the mental-math rule tracks the forecast in regular structures and is
                # an upper bound in fast ones, where shallow stacks keep busting on the bubble
                fc = L.forecast(remaining, paid, avg, bl)
                slow = L.fold_cost(round(fc.mean), fc.blinds, 8)
                self.assertGreaterEqual(slow, cost)
                ratio = slow / L.expected_cost(avg, remaining, paid)
                self.assertLess(ratio, 1.30, (speed, remaining, paid, slow))
                if speed in ("regular", "slow"):
                    self.assertGreater(ratio, 0.70, (speed, remaining, paid, slow))
        self.assertEqual(L.expected_cost(30000, 150, 150), 0.0)
        self.assertGreater(L.expected_cost(30000, 330, 300), 0.0)

    def test_bubble_slows_down(self):
        """The last tenth of the eliminations takes far longer than the rest, as measured."""
        L = self.L
        bl = L.Blinds(1.259, 15 * L.HANDS_PER_MINUTE)       # 15-minute levels
        # GGPoker bracelet event: 372 left at the close, 134 paid, average 25.8bb; the bubble
        # burst 104 minutes of play later with the big blind 4.2 times higher
        hands, stall, pace = L.bubble_path(372, 134, 25.8, bl)
        clock = stall + (hands - stall) * pace
        self.assertTrue(85 <= clock / L.HANDS_PER_MINUTE <= 125, clock)
        self.assertTrue(3.0 <= bl.mult(clock) <= 5.5)
        plain = L.hands_to_bubble(372, 134, 25.8, bl, near=1.0, hfh=1.0)
        self.assertGreater(hands, plain * 1.2)
        # hand-for-hand: the blinds keep rising while fewer hands are dealt
        warped = L.forecast(372, 134, 25.8, bl).blinds
        self.assertIsNotNone(warped.stall_from)
        self.assertGreaterEqual(warped.mult(warped.stall_from + 10), bl.mult(warped.stall_from + 10))
        self.assertTrue(2 <= L.hfh_left(134) <= 7)

    def test_forecast(self):
        L, bl = self.L, self.turbo
        near, far = L.forecast(180, 150, 25.0, bl), L.forecast(450, 150, 25.0, bl)
        for fc in (near, far):
            self.assertAlmostEqual(fc.alive[0], 1.0)
            self.assertAlmostEqual(fc.alive[-1], 0.0)
            self.assertTrue(all(a >= b - 1e-12 for a, b in zip(fc.alive, fc.alive[1:])))
            self.assertLessEqual(fc.quantile(0.05), fc.quantile(0.5))
            self.assertLessEqual(fc.quantile(0.5), fc.quantile(0.95))
        self.assertLess(near.mean, far.mean)
        self.assertEqual(L.forecast(150, 150, 25.0, bl).mean, 0.0)

    def test_plan_is_the_best_of_the_policies(self):
        L, bl = self.L, self.turbo
        fc = L.forecast(300, 150, 30.0, bl)
        reward = L.bubble_reward(600, 150, None, 1.0, 300 * 30.0)
        plans = {pol: L.solve(15.0, fc, bl, reward=reward, policy=pol, grid=120) for pol in ("itm", "fold", "nash", "ev")}
        best = plans["itm"]
        self.assertGreater(best.itm, plans["fold"].itm)
        self.assertGreaterEqual(best.itm + 1e-9, plans["nash"].itm)
        self.assertGreaterEqual(best.itm + 1e-9, plans["ev"].itm)
        self.assertGreaterEqual(plans["ev"].prize + 1e-9, best.prize)
        self.assertTrue(0.0 < best.itm < 1.0)
        # a bigger stack never hurts
        chances = [best.chance(0, 4, b) for b in (4, 8, 15, 30, 60)]
        self.assertTrue(all(a <= b + 1e-9 for a, b in zip(chances, chances[1:])), chances)
        # premiums before trash, and the range never includes the big blind's seat
        rng = best.shove_range(0, 2, 15.0)
        self.assertGreaterEqual(rng[HAND_INDEX["AA"]], rng[HAND_INDEX["72o"]])
        self.assertEqual(sum(best.shove_range(0, 0, 15.0)), 0.0)

    def test_safe_stack_sits_out(self):
        L, bl = self.L, self.turbo
        fc = L.forecast(165, 150, 25.0, bl)
        self.assertGreaterEqual(L.sit_out_line(25.0, 165, 150), L.safe_stack(fc, bl, 8, 0.95) * 0.9)
        plan = L.solve(30.0, fc, bl, grid=120)
        self.assertGreater(plan.fold_only, 0.97)
        self.assertGreater(plan.itm, 0.97)
        for seat in range(1, 8):
            self.assertLess(range_pct(plan.shove_range(0, seat, 30.0)), 1.5)
        self.assertGreaterEqual(L.safe_stack(fc, bl, 8, 0.99), L.safe_stack(fc, bl, 8, 0.9))

    def test_zones_and_scout(self):
        L = self.L
        # 240 left, 200 paid: the line is one average stack
        self.assertAlmostEqual(L.sit_out_line(50000, 240, 200), 50000.0)
        self.assertEqual(L.zone(70000, 50000, 240, 200)[0], "safe")
        self.assertEqual(L.zone(40000, 50000, 240, 200)[0], "close")
        self.assertEqual(L.zone(15000, 50000, 240, 200)[0], "short")
        self.assertEqual(L.zone(1000, 50000, 600, 200)[0], "far")
        self.assertEqual(L.zone(1, 50000, 200, 200)[0], "safe")
        lines = [L.sit_out_line(50000, r, 200) for r in (201, 205, 220, 240, 300, 400, 600, 900)]
        self.assertTrue(all(a < b for a, b in zip(lines, lines[1:])), lines)
        self.assertTrue(all(L.cash_chance(a) <= L.cash_chance(b) for a, b in ((0.0, 0.1), (0.1, 0.3), (0.3, 1.0))))
        self.assertIn("SIT OUT", L.describe_zone(70000, 50000, 240, 200))
        self.assertIn("KEEP PLAYING", L.describe_zone(5000, 50000, 400, 200))
        self.assertEqual([L.seat_name(b, 8) for b in range(7, 0, -1)], ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB"])
        self.assertEqual([L.seat_name(b, 6) for b in range(5, -1, -1)], ["LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(L.seat_name(6, 7), "UTG")
        ordinary = L.scout(16, 500, 150, entrants=1000, speed="turbo", buyin=10, fee=0.8)
        close = L.scout(16, 190, 150, entrants=320, speed="turbo", buyin=10, fee=0.8)
        self.assertLess(ordinary.itm, 0.30)
        self.assertGreater(close.itm, 0.55)
        self.assertLess(ordinary.cover, close.cover)
        self.assertEqual(ordinary.verdict, "SKIP")
        self.assertLessEqual(ordinary.itm, ordinary.best_itm + 1e-9)
        # without a min-cash the scout assumes GGPoker's usual two full prices, and says so
        self.assertTrue(ordinary.assumed_min_cash)
        self.assertAlmostEqual(ordinary.min_cash, 2.0, places=2)
        self.assertIn("(assumed)", L.describe(ordinary))
        bounty = L.scout(16, 500, 150, entrants=1000, speed="turbo", buyin=10, fee=0.8, bounty_share=0.5)
        self.assertLess(bounty.min_cash, ordinary.min_cash)
        self.assertLess(bounty.roi, ordinary.roi)
        fixed = L.payouts_with_min_cash(1000, 150, 10000.0, 21.0)
        self.assertAlmostEqual(fixed[-1], 21.0)
        self.assertAlmostEqual(sum(fixed), 10000.0, places=4)

    def test_reference_charts(self):
        L = self.L
        charts = L.reference_charts(8)
        wide, short, tight = charts["wide"], charts["short"], charts["tight"]
        self.assertEqual(list(wide["open"]), ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB"])
        widths = [range_pct(w) for w in wide["open"].values()]
        self.assertTrue(all(a <= b + 1e-9 for a, b in zip(widths, widths[1:])), widths)   # later seats shove wider
        for k, (seat, w) in enumerate(wide["open"].items()):
            t = tight["open"][seat]
            self.assertTrue(all(a >= b for a, b in zip(w, t)), seat)       # tight sits inside wide
            self.assertEqual(w[HAND_INDEX["AA"]], 1.0)
            self.assertEqual(t[HAND_INDEX["KK"]], 1.0)
            self.assertEqual(w[HAND_INDEX["72o"]], 0.0)
            # tighter than chip-EV shove-or-fold: a called loss ends the tournament
            self.assertLess(range_pct(w), range_pct(nash_push_range(7 - k, 10.0)))
            # a 4bb stack cannot wait: it shoves wider than the 10bb chart from the early seats
            if k < 5:
                self.assertGreater(range_pct(short["open"][seat]), range_pct(w))
        for ch in (wide, short, tight):
            # an early raiser is stronger than a late one
            self.assertLessEqual(range_pct(ch["early"]), range_pct(ch["late"]) + 1e-9)
        self.assertLess(range_pct(tight["late"]), range_pct(wide["late"]))

    def test_playbook_prints_the_engine_charts(self):
        # the charts in PLAYBOOK.md are the ones the calculator plays, and its sit-out line is the engine's
        L = self.L
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PLAYBOOK.md")) as fh:
            text = fh.read()
        section = text[text.index("## Late-registration min-cash plan"):]
        charts = L.reference_charts(8)
        for seat in charts["wide"]["open"]:
            row = " | ".join([seat] + [format_range(charts[name]["open"][seat]) for name in ("wide", "short", "tight")])
            self.assertIn(f"| {row} |", section)
        for kind in ("late", "early"):
            row = " | ".join(format_range(charts[name][kind]) for name in ("wide", "short", "tight"))
            self.assertIn(f"| {row} |", section)
        ratios = [x for x, _ in L.SIT_OUT_TABLE[1:9]]
        self.assertIn("| " + " | ".join(f"{x:.2f}" for x in ratios) + " |", section)
        self.assertIn("| " + " | ".join(f"{y:.2f}" for _, y in L.SIT_OUT_TABLE[1:9]) + " |", section)

    def test_sheet_is_what_gets_delivered(self):
        """The printed rules, played exactly, cash a little less than the solver and more than folding."""
        L, bl = self.L, self.turbo
        fc = L.forecast(400, 150, 27.5, bl)
        best = L.solve(11.0, fc, bl, grid=120)
        sheet = L.sheet_plan(11.0, fc, bl, grid=120)
        self.assertLessEqual(sheet.itm, best.itm + 1e-9)
        self.assertGreater(sheet.itm, best.itm - 0.08)
        self.assertGreater(sheet.itm, best.fold_only)
        rules = L.build_sheet(8)
        self.assertIsNone(rules.pick(1.2, 10.0))
        self.assertEqual(rules.pick(0.7, 10.0), "aces")
        self.assertEqual(rules.pick(0.3, 10.0), "tight")
        self.assertEqual(rules.pick(0.1, 10.0), "wide")
        self.assertEqual(rules.pick(0.1, 4.0), "short")
        self.assertEqual(rules.pick(0.1, 30.0), "premium")
        # the raiser is called first: a short re-shove gets the equity against a raising range, not random cards
        fe, eq = L.spots(8)["raise"][("late", 3.0)]
        self.assertLess(eq[HAND_INDEX["K9s"]], 0.5)
        self.assertLess(fe[HAND_INDEX["K9s"]], 0.05)
        # walks are rare: the small blind usually plays when it is folded to
        self.assertLess(L._folded_to(8)[0], 0.10)

    def test_sit_out_line_grows_in_small_fields(self):
        L = self.L
        big, mid, small = (L.sit_out_line(1.0, round(p * 1.2), p) for p in (300, 60, 15))
        self.assertAlmostEqual(big, 1.0)
        self.assertGreater(mid, big + 0.3)
        self.assertGreater(small, mid + 1.0)
        # where no extra is added the line is safe in the forecast
        for speed, avg in (("turbo", 25.0), ("regular", 30.0)):
            sp = L.SPEEDS[speed]
            bl = L.Blinds(sp["growth"], sp["hands_per_level"])
            for paid in (30, 60, 150):
                fc = L.forecast(round(paid * 1.2), paid, avg, bl)
                line = L.sit_out_line(avg, round(paid * 1.2), paid)
                self.assertGreater(L.fold_only_chance(line, fc, bl), 0.90, (speed, paid))

    def test_cli(self):
        for args, code in ((["latereg", "--stack-bb", "16", "--left", "190", "--paid", "150", "--entries", "1000"], 0),
                           (["latereg-chart"], 0),
                           (["latereg", "--stack-bb", "10", "--left", "2000", "--entries", "4500", "--levels-left", "4"], 0),
                           (["latereg", "--stack", "8000", "--bb", "500", "--left", "26", "--paid", "8",
                             "--avg", "16320", "--buyin", "27.6", "--fee", "2.4", "--chart"], 0),
                           (["latereg-safe", "--stack", "34k", "--avg", "52000", "--left", "180", "--paid", "150"], 0),
                           (["latereg", "--stack-bb", "16", "--left", "190", "--paid", "150"], 2)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                got = main(args)
            self.assertEqual(got, code, (args, err.getvalue()))


class AllInOrFoldTournament(unittest.TestCase):
    """The whole-tournament all-in or fold tables (poker_coach/binary.py)."""

    @classmethod
    def setUpClass(cls):
        from poker_coach import binary
        cls.B = binary

    def test_data(self):
        B = self.B
        self.assertEqual(B.data()["version"], B.DATA_VERSION)
        d = B.table(8)
        allowed = set(B.STACKS) | {0}
        for stage in B.STAGES:
            for nb in B.SEATS:
                lim = B.limits(stage, nb)
                self.assertEqual(len(lim), 169)
                self.assertTrue(set(lim) <= allowed)
                self.assertEqual(lim[HAND_INDEX["AA"]], B.TOP)        # aces at any depth
                self.assertEqual(lim[HAND_INDEX["KK"]], B.TOP)
                self.assertLessEqual(lim[HAND_INDEX["72o"]], 4)        # trash only when nearly out of chips
        # the late entry the plan is solved for: cashes about one time in six, and is no winner by itself
        self.assertTrue(0.12 < d["entry_result"]["cash"] < 0.22)
        self.assertLess(d["entry_result"]["return"], 0.0)

    def test_ranges_make_sense(self):
        B = self.B
        for stage in B.STAGES:
            for s in (6, 10, 15, 25):
                widths = [B.width(stage, nb, s) for nb in sorted(B.SEATS, reverse=True)]
                self.assertTrue(all(a <= b + 2.0 for a, b in zip(widths, widths[1:])), (stage, s, widths))
            for nb in B.SEATS:
                by_stack = [B.width(stage, nb, s) for s in (6, 8, 10, 12, 15, 20, 25, 30, 40)]
                self.assertTrue(all(a >= b for a, b in zip(by_stack, by_stack[1:])), (stage, nb, by_stack))
                # far tighter than a chip-EV push/fold chart, at the stacks a late entry has
                for s in (8, 10, 12, 15):
                    self.assertLess(B.width(stage, nb, s), range_pct(nash_push_range(nb, s)))
        # before the money is the tighter of the two stages for a short stack
        self.assertLess(B.width("before", 1, 10), B.width("money", 1, 10))
        self.assertEqual(format_range(B.first_in_range("before", 2, 60)), "KK+")

    def test_tables(self):
        B = self.B
        d = B.table(8)
        for stage in B.STAGES:
            for key, _label, _nb in B.RAISERS:
                row = d["reshove"][stage][key]
                self.assertEqual(len(row), len(B.BANDS))
                for rng in row:
                    self.assertGreaterEqual(parse_range(rng)[HAND_INDEX["AA"]], 0.5)
            # over an early raise the range is tighter than over a late one, and that tighter than a steal
            for i in range(len(B.BANDS)):
                e, l, s = (range_pct(parse_range(d["reshove"][stage][k][i])) for k in ("early", "late", "steal"))
                self.assertLessEqual(e, l)
                self.assertLessEqual(l, s)
        for key, _label, _nb in B.SHOVERS:
            for i in range(len(B.BANDS)):
                normal = parse_range(d["call"]["normal"][key][i])
                bubble = parse_range(d["call"]["bubble"][key][i])
                self.assertTrue(all(a >= b for a, b in zip(normal, bubble)), (key, i))   # the bubble only removes hands
                self.assertGreaterEqual(bubble[HAND_INDEX["AA"]], 0.5)
            sizes = [range_pct(parse_range(r)) for r in d["call"]["normal"][key]]
            self.assertTrue(all(a >= b for a, b in zip(sizes, sizes[1:])), (key, sizes))  # bigger all-in, fewer calls
        self.assertEqual([B.band(s) for s in (3, 7, 8, 11, 12, 16, 17, 24, 25, 40)], [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    def test_decisions(self):
        B = self.B
        h = HAND_INDEX
        self.assertEqual(B.decide(h["A8o"], 2, 12)[0], "ALL-IN")
        self.assertEqual(B.decide(h["A8o"], 7, 12)[0], "FOLD")
        self.assertEqual(B.decide(h["AA"], 7, 35)[0], "ALL-IN")
        self.assertEqual(B.decide(h["QQ"], 4, 60)[0], "FOLD")                 # deep: aces and kings only
        self.assertEqual(B.decide(h["72o"], 0, 10)[0], "CHECK")               # unraised big blind
        self.assertEqual(B.decide(h["99"], 2, 15, facing="raise", facing_seat=3)[0], "ALL-IN")
        self.assertEqual(B.decide(h["KJo"], 2, 15, facing="raise", facing_seat=7)[0], "FOLD")
        self.assertEqual(B.decide(h["QQ"], 2, 20, facing="allin", facing_seat=6, allin_bb=20)[0], "CALL")
        self.assertEqual(B.decide(h["A9o"], 2, 20, facing="allin", facing_seat=6, allin_bb=20)[0], "FOLD")
        # the big blind gets a better price: one stack band wider
        self.assertEqual(B.decide(h["ATo"], 2, 30, facing="allin", facing_seat=3, allin_bb=14)[0], "CALL")
        self.assertEqual(B.decide(h["A9s"], 2, 30, facing="allin", facing_seat=3, allin_bb=14)[0], "FOLD")
        self.assertEqual(B.decide(h["A9s"], 0, 30, facing="allin", facing_seat=3, allin_bb=14)[0], "CALL")
        # and the bubble takes hands away
        self.assertEqual(B.decide(h["ATo"], 2, 30, facing="allin", facing_seat=3, allin_bb=14, bubble=True)[0], "FOLD")
        # two all-ins in front: short stacks call with much more than aces and kings, deep ones do not
        self.assertEqual(B.decide(h["TT"], 2, 10, facing="allins")[0], "CALL")
        self.assertEqual(B.decide(h["99"], 2, 10, facing="allins")[0], "FOLD")
        self.assertEqual(B.decide(h["QQ"], 2, 20, facing="allins", allin_bb=20)[0], "CALL")
        self.assertEqual(B.decide(h["JJ"], 2, 20, facing="allins", allin_bb=20)[0], "FOLD")
        self.assertEqual(B.decide(h["JJ"], 0, 20, facing="allins", allin_bb=20)[0], "CALL")     # the big blind's price
        self.assertEqual(B.decide(h["QQ"], 2, 20, facing="allins", allin_bb=20, bubble=True)[0], "FOLD")
        self.assertEqual(B.decide(h["AA"], 2, 35, facing="allins", bubble=True)[0], "CALL")
        for players in B.TABLES:
            two = B.table(players)["call"]
            widths = [range_pct(parse_range(r)) for r in two["normal"]["two"]]
            self.assertTrue(all(a >= b for a, b in zip(widths, widths[1:])), (players, widths))
            for i in range(len(B.BANDS)):
                normal, bubble = parse_range(two["normal"]["two"][i]), parse_range(two["bubble"]["two"][i])
                self.assertTrue(all(a >= b for a, b in zip(normal, bubble)), (players, i))
                # tighter than calling one all-in from a late seat of the same size
                one = parse_range(two["normal"]["late"][i])
                self.assertTrue(all(a >= b for a, b in zip(one, normal)), (players, i))
        with self.assertRaises(ValueError):
            B.decide(h["AA"], 2, 10, stage="early")

    def test_six_and_seven_players(self):
        B = self.B
        h = HAND_INDEX
        self.assertEqual(list(B.seats(8).values()), ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB"])
        self.assertEqual(list(B.seats(7).values()), ["UTG", "LJ", "HJ", "CO", "BTN", "SB"])
        self.assertEqual(list(B.seats(6).values()), ["LJ", "HJ", "CO", "BTN", "SB"])
        self.assertEqual([r[1] for r in B.raisers(6)][0], "LJ")
        self.assertEqual([r[1] for r in B.raisers(7)][0], "UTG or LJ")
        with self.assertRaises(ValueError):
            B.table(9)
        for players in (6, 7):
            d = B.table(players)
            self.assertEqual(set(d["first_in"]["before"]), {str(nb) for nb in B.seats(players)})
            rows = B.first_in_rows("before", players)
            self.assertEqual(len(rows), players - 1)
            for nb in B.seats(players):
                self.assertEqual(B.limit("before", nb, "AA", players), B.TOP)
                self.assertLessEqual(B.limit("before", nb, "72o", players), 4)
                # with the same number of players behind the range stays close to the 8-handed one:
                # the blinds come round sooner (wider), and there is less ante money to win (tighter)
                self.assertLess(abs(B.width("before", nb, 10, players) - B.width("before", nb, 10, 8)), 6.0)
            widths = [B.width("before", nb, 10, players) for nb in B.seats(players)]
            self.assertTrue(all(a <= b + 2.0 for a, b in zip(widths, widths[1:])), (players, widths))
            for key, _label, _nb in B.shovers(players):
                for i in range(len(B.BANDS)):
                    normal, bubble = (parse_range(d["call"][k][key][i]) for k in ("normal", "bubble"))
                    self.assertTrue(all(a >= b for a, b in zip(normal, bubble)), (players, key, i))
            self.assertTrue(0.12 < d["entry_result"]["cash"] < 0.24)
            self.assertLess(d["entry_result"]["return"], 0.0)
        # six-handed the first seat has five players behind: its name is LJ, and UTG does not exist
        self.assertEqual(B.decide(h["A9o"], 5, 10, players=6)[0], "ALL-IN")
        self.assertIn("LJ", B.decide(h["A9o"], 5, 10, players=6)[1])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(main(["binary", "--hand", "A9o", "--pos", "LJ", "--stack", "10", "--players", "6"]), 0)
            self.assertEqual(main(["binary-sheet", "--players", "7"]), 0)
            self.assertEqual(main(["binary-chart", "--pos", "BTN", "--players", "6"]), 0)
            self.assertEqual(main(["binary", "--hand", "A9o", "--pos", "BTN", "--stack", "10", "--players", "5"]), 2)
        self.assertIn("6-handed", out.getvalue())
        self.assertIn("ALL-IN OR FOLD, the whole tournament (7-handed)", out.getvalue())

    def test_cli_and_playbook(self):
        B = self.B
        for args, word in ((["binary", "--hand", "A8o", "--pos", "BTN", "--stack", "12"], "ALL-IN"),
                           (["binary", "--hand", "T9s", "--pos", "UTG", "--stack", "12", "--stage", "money"], "FOLD"),
                           (["binary", "--hand", "99", "--pos", "BTN", "--stack", "15", "--facing", "CO raise"], "ALL-IN"),
                           (["binary", "--hand", "AJo", "--pos", "SB", "--stack", "20", "--facing", "BTN allin 9",
                             "--bubble"], "FOLD"),
                           (["binary", "--hand", "TT", "--pos", "BTN", "--stack", "10", "--facing", "HJ allin, CO allin"],
                            "CALL"),
                           (["binary", "--hand", "AKo", "--pos", "BTN", "--stack", "20", "--facing",
                             "HJ raise, CO allin 20"], "FOLD"),
                           (["binary-chart", "--pos", "SB"], "SB, before the money"),
                           (["binary-sheet"], "One all-in before you")):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(args), 0, args)
            self.assertIn(word, out.getvalue(), args)
        # the tables printed in PLAYBOOK.md are the ones the command answers from
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PLAYBOOK.md")) as fh:
            text = fh.read()
        section = text[text.index("## All-in or fold for a whole tournament"):]
        d = B.table(8)
        for rows in (d["reshove"]["before"], d["call"]["normal"], d["call"]["bubble"]):
            for cells in rows.values():
                self.assertIn("| " + " | ".join(cells) + " |", section)
        for nb in B.SEATS:
            row = " | ".join(f"{B.width('before', nb, s):.0f}%" for s in (6, 8, 10, 12, 15, 20, 25, 30, 40))
            self.assertIn(f"| {B.SEATS[nb]} | {row} |", section)
        for nb, cells in B.first_in_rows("before").items():
            self.assertEqual(len(cells), len(B.BANDS))
            self.assertIn(f"| {B.SEATS[nb]} | " + " | ".join(cells) + " |", section)
        for players in (6, 7):
            for nb, cells in B.first_in_rows("before", players).items():
                self.assertIn(f"| {B.seat_name(nb, players)} | " + " | ".join(cells) + " |", section)
        # a cell splits into pairs, suited and offsuit hands, and nothing is lost in the split
        rng = B.first_in_range("before", 2, 10)
        pairs, suited, offsuit = B.range_groups(rng)
        self.assertEqual((pairs, suited, offsuit), ("22+", "A2s+, K8s+, QTs+, JTs", "A2o+, K9o+, QJo"))
        self.assertEqual(format_range(rng), ", ".join((pairs, suited, offsuit)))


class Spins(unittest.TestCase):
    """All-in or fold for 3-player winner-take-all games (poker_coach/spin.py)."""

    @classmethod
    def setUpClass(cls):
        from poker_coach import spin
        cls.S = spin

    def test_data(self):
        S = self.S
        d = S.data()
        self.assertEqual(d["version"], S.DATA_VERSION)
        for n, spots in (("3", ["0:0", "1:0", "1:1", "2:1", "2:2", "2:3"]), ("2", ["0:0", "1:1"])):
            self.assertEqual(sorted(d["games"][n], key=float), [f"{s:g}" for s in S.STACKS])
            for stack, game in d["games"][n].items():
                for vs in S.PROFILES:
                    for key in spots:
                        self.assertEqual(len(game["play"][vs][key]), 169, (n, stack, vs, key))
                        self.assertEqual(len(game["ev"][vs][key]), 169)
                # the tidied table gives nothing away against players who call correctly
                self.assertLess(abs(sum(game["value"]["solid|solid"])) / int(n), 0.004, (n, stack))
        self.assertEqual(set(d["raise"]), set(S.OPENERS))

    def test_ranges_make_sense(self):
        S = self.S
        # heads-up at 10 big blinds is the textbook solution: all-in about 58%, call about 37%
        self.assertTrue(55 < S.width("hu_sb", 10) < 62, S.width("hu_sb", 10))
        self.assertTrue(34 < S.width("hu_bb", 10) < 41, S.width("hu_bb", 10))
        aa, seven_two = HAND_INDEX["AA"], HAND_INDEX["72o"]
        for spot in S.SPOTS:
            widths = [S.width(spot, s) for s in S.STACKS if s >= 4]
            for a, b in zip(widths, widths[1:]):
                self.assertLess(b, a + 2.5, (spot, widths))           # deeper stacks never play clearly more hands
            for s in S.STACKS:
                self.assertEqual(S.play(spot, s)[aa], 1.0, (spot, s))
            self.assertEqual(S.play(spot, 12)[seven_two], 0.0, spot)
        for s in (8, 10, 15, 20):
            # a second all-in in front shrinks the call; the button is tighter than the small blind
            self.assertLess(S.width("bb_vs_both", s), S.width("bb_vs_btn", s))
            self.assertLess(S.width("bb_vs_btn", s), S.width("bb_vs_sb", s))
            self.assertLess(S.width("btn", s), S.width("sb", s))
            # against players who call too much the steals shrink
            for spot in ("btn", "sb", "hu_sb"):
                self.assertLess(S.width(spot, s, "loose"), S.width(spot, s) - 3, (spot, s))

    def test_wider_than_the_tournament_tables(self):
        from poker_coach import binary as B
        S = self.S
        for s in (6, 10, 15):
            self.assertGreater(S.width("btn", s), B.width("before", 2, s, 6) + 3, s)
            self.assertGreater(S.width("sb", s), B.width("before", 1, s, 6) + 8, s)

    def test_tidy(self):
        S = self.S
        ev = [-1.0] * 169
        for h in ("AA", "KK", "QQ", "AKs", "AQs", "ATs", "A5s", "AKo"):
            ev[HAND_INDEX[h]] = 1.0
        ev[HAND_INDEX["AJs"]] = -0.5                      # a gap worth filling: AQs, AJs, ATs earn 1.5 together
        got = S.tidy(ev)
        self.assertEqual(format_range([float(x) for x in got]), "QQ+, ATs+, AKo")
        # every printed range reads without gaps
        for vs in S.PROFILES:
            for spot, row in S.rows(vs).items():
                for text in row:
                    self.assertNotIn("-", text, (vs, spot, text))

    def test_values(self):
        S = self.S
        for n in (2, 3):
            for s in (6, 8, 10, 12, 15):
                # the reply to loose callers beats the standard table against them, and costs little otherwise
                self.assertGreater(S.value(n, s, "loose", "loose"), S.value(n, s, "solid", "loose") + 0.005, (n, s))
                self.assertGreater(S.value(n, s, "solid", "loose"), 0.01, (n, s))
                self.assertGreater(S.value(n, s, "loose", "solid"), -0.012, (n, s))
                self.assertGreater(S.value(n, s, "solid", "vloose"), S.value(n, s, "solid", "loose"), (n, s))

    def test_money(self):
        S = self.S
        self.assertAlmostEqual(sum(share for _m, share, _p in S.PRIZES), 1.0, places=6)
        self.assertAlmostEqual(sum(S.average_prizes()), 3 * (1 - S.FEE), places=3)
        self.assertAlmostEqual(S.roi(1 / 3), -S.FEE, places=3)
        self.assertTrue(0.357 < S.break_even() < 0.361, S.break_even())
        self.assertGreater(S.break_even(False), S.break_even())
        self.assertAlmostEqual(S.roi(S.break_even()), 0.0, places=6)
        self.assertTrue(0.3 < S.roi(0.5) < 0.4)             # half the games would be +38%: nobody does that

    def test_decisions(self):
        S = self.S
        aa, trash = HAND_INDEX["AA"], HAND_INDEX["72o"]
        for spot in S.SPOTS:
            action, why = S.decide(aa, spot, 10)
            self.assertEqual(action, "ALL-IN" if S.SPOTS[spot][3] == "all-in" else "CALL", spot)
            self.assertIn("bb", why)
            self.assertEqual(S.decide(trash, spot, 15)[0], "FOLD", spot)
        self.assertEqual(S.decide(trash, "bb_vs_sb_limp", 15)[0], "CHECK")
        self.assertEqual(S.decide(aa, "bb_vs_sb_limp", 15)[0], "ALL-IN")
        self.assertEqual(S.decide(trash, "bb_vs_btn_raise", 15)[0], "FOLD")
        # a small raise from a very short stack is answered as an all-in
        action, why = S.decide(HAND_INDEX["KJo"], "bb_vs_btn_raise", 4)
        self.assertEqual(action, "CALL")
        self.assertIn("is an all-in", why)
        # the edge is in big blinds, not in the solver's hundredths
        self.assertTrue(0 < S.edge("btn", 10, "AA") < 12)
        with self.assertRaises(ValueError):
            S.decide(aa, "btn", 10, "wild")
        with self.assertRaises(ValueError):
            S.decide(aa, "utg", 10)

    def test_simulation(self):
        import os
        import sys
        S = self.S
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import spin_sim as M
        self.assertAlmostEqual(sum(v[3] for v in M.STRUCTURES.values()), sum(sh for m, sh, _p in S.PRIZES if m <= 10), places=3)
        games, wins, hands = M.play_games(("sheet", "calls:1", "x3", 1500, 5, M.HANDS_PER_MINUTE))
        self.assertEqual(games, 1500)
        self.assertTrue(0.28 < wins / games < 0.39, wins / games)
        self.assertTrue(8 < hands / games < 25, hands / games)
        # the stored results: an even game against correct callers, more against loose ones, never half
        sim = S.sim()
        self.assertEqual(set(sim["results"]), set(M.STRUCTURES))
        for hero in ("sheet", "sheet-loose"):
            self.assertTrue(0.32 < S.simulated_win(hero, "solid") < 0.34, hero)
            self.assertGreater(S.simulated_win(hero, "loose"), S.simulated_win(hero, "solid") + 0.005)
            self.assertGreater(S.simulated_win(hero, "vloose"), S.simulated_win(hero, "loose"))
            self.assertLess(S.simulated_win(hero, "vloose"), 0.40)
        self.assertGreater(S.simulated_win("sheet-loose", "loose"), S.simulated_win("sheet", "loose"))
        # the tournament tables are too tight for a game with one prize
        self.assertLess(S.simulated_win("mtt", "solid"), S.simulated_win("sheet", "solid") - 0.005)
        self.assertLess(S.simulated_roi("sheet", "solid"), -0.05)

    def test_cli_and_playbook(self):
        import io
        import os
        from contextlib import redirect_stderr, redirect_stdout
        from poker_coach.cli import main
        S = self.S
        for args, expect in (
                (["spin", "--hand", "K7s", "--pos", "BTN", "--stack", "12"], "ALL-IN"),
                (["spin", "--hand", "72o", "--pos", "BTN", "--stack", "12"], "FOLD"),
                (["spin", "--hand", "A5o", "--pos", "BB", "--stack", "9", "--shoved", "BTN"], "CALL"),
                (["spin", "--hand", "98s", "--pos", "BB", "--stack", "10", "--shoved", "BTN,SB"], "FOLD"),
                (["spin", "--hand", "Q8o", "--pos", "SB", "--stack", "11", "--players", "2"], "ALL-IN"),
                (["spin", "--hand", "Q8o", "--pos", "BTN", "--stack", "11", "--players", "2", "--vs", "loose"], "ALL-IN"),
                (["spin", "--hand", "K4o", "--pos", "BB", "--stack", "20", "--players", "2", "--shoved", "SB"], "FOLD"),
                (["spin", "--hand", "KJo", "--pos", "BB", "--stack", "14", "--facing", "SB limp"], "ALL-IN"),
                (["spin", "--hand", "83o", "--pos", "BB", "--stack", "14", "--facing", "SB limp"], "CHECK"),
                (["spin", "--hand", "T9s", "--pos", "BB", "--stack", "12", "--players", "2", "--facing", "SB raise"], "ALL-IN"),
                (["spin", "--hand", "AJo", "--pos", "SB", "--stack", "15", "--facing", "BTN raise"], "ALL-IN"),
                (["spin-sheet"], "THREE PLAYERS"),
                (["spin-sheet", "--vs", "loose"], "1.5 times too wide"),
                (["spin-odds"], "break even: win 35.9%"),
                (["spin-odds", "--win", "38"], "win 38%: +5.6%")):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(args), 0, args)
            self.assertIn(expect, out.getvalue(), args)
        for args in (["spin", "--hand", "AA", "--pos", "UTG", "--stack", "10"],
                     ["spin", "--hand", "AA", "--pos", "BTN", "--stack", "10", "--shoved", "SB"],
                     ["spin", "--hand", "AA", "--pos", "BB", "--stack", "10", "--players", "4"],
                     ["spin", "--hand", "AA", "--pos", "BTN", "--stack", "10", "--facing", "SB limp"]):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                self.assertNotEqual(main(args), 0, args)
        # the playbook prints the engine's tables
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "PLAYBOOK.md")) as fh:
            book = fh.read()
        for vs, spots in (("solid", list(S.SPOTS)), ("loose", ["btn", "sb", "hu_sb"])):
            for spot in spots:
                for (label, _s), text in zip(S.BANDS, S.rows(vs)[spot]):
                    self.assertIn(f"| {label} | {text} |", book, (vs, spot, label))
        for spot, row in S.raise_rows().items():
            for k, text in enumerate(row):
                if not (spot in S.AS_ALLIN and k == 0):
                    self.assertIn(text, book, (spot, k))
        self.assertIn(f"{100 * S.break_even():.1f}%", book)


class TagSheet(unittest.TestCase):
    """The tight-aggressive sheet for 6, 7 and 8 players (poker_coach/tag.py)."""

    @classmethod
    def setUpClass(cls):
        from poker_coach import binary, tag
        cls.T, cls.B = tag, binary

    @staticmethod
    def has(text: str, hand: str) -> bool:
        return bool(text) and text != "nothing" and parse_range(text)[HAND_INDEX[hand]] >= 0.5

    @staticmethod
    def inside(small: str, big: str) -> bool:
        a = parse_range(small) if small and small != "nothing" else [0.0] * 169
        b = parse_range(big) if big and big != "nothing" else [0.0] * 169
        return all(y >= 0.5 for x, y in zip(a, b) if x >= 0.5)

    def test_data(self):
        T, B = self.T, self.B
        self.assertEqual(T.data()["version"], T.DATA_VERSION)
        self.assertEqual(T.order(8), ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(T.order(6), ["LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(T.groups(6), ["middle", "late", "sb"])
        self.assertEqual(T.group_label("early", 8), "UTG or UTG+1")
        self.assertEqual(T.group_label("early", 7), "UTG")
        for players in T.TABLES:
            t = T.table(players)
            self.assertEqual(set(t["first_in"]), {str(nb) for nb in T.seats(players)})
            # every seat but the first can have callers in front, the big blind included
            self.assertEqual(set(t["limpers"]), {str(nb) for nb in range(players - 2, -1, -1)})
            self.assertEqual({k.split("|")[0] for k in t["vs_raise"]}, set(T.groups(players)))
            for part in ("reraised", "shoved_on"):
                self.assertEqual(list(t[part]), T.groups(players))
            self.assertEqual(list(t["cold"]), [g for g in T.groups(players) if g != "sb"])
            self.assertEqual(t["call"], B.table(players)["call"])
        with self.assertRaises(ValueError):
            T.table(9)

    def test_first_in(self):
        T, B = self.T, self.B
        for players in T.TABLES:
            t = T.table(players)["first_in"]
            for nb in T.seats(players):
                row = t[str(nb)]
                self.assertEqual(row["raise"][0], format_range(rfi_range(nb, 100.0)))
                self.assertTrue(self.inside(row["raise"][1], row["raise"][0]), (players, nb))
                for s, text in zip(T.SHORT_STACKS, row["allin"]):
                    self.assertEqual(text, format_range(B.first_in_range("before", nb, s, players)))
                self.assertTrue(self.has(row["raise"][0], "AA") and self.has(row["allin"][0], "AA"))
            # later seats raise more hands
            widths = [sum(parse_range(t[str(nb)]["raise"][0])) for nb in range(players - 1, 1, -1)]
            self.assertEqual(widths, sorted(widths))

    def test_limpers(self):
        T, B = self.T, self.B
        for players in T.TABLES:
            t = T.table(players)["limpers"]
            for nb, row in t.items():
                self.assertEqual(len(row["raise"]), min(3, players - 1 - int(nb)), (players, nb))
                for a, b in zip(row["raise"], row["raise"][1:]):
                    self.assertTrue(self.inside(b, a), (players, nb))       # more callers, fewer raises
                for hand in ("AA", "99", "AJs", "AQo", "KQs"):
                    self.assertTrue(all(self.has(r, hand) for r in row["raise"]), (players, nb, hand))
                self.assertFalse(self.has(row["raise"][0], "72o"))
                # 16bb or less: the all-in hands of the seat before (the big blind: the small blind's)
                self.assertEqual(row["allin"], [format_range(B.first_in_range("before", int(nb) + 1, s, players))
                                                for s in T.SHORT_STACKS])
                for text in row["call"]:
                    self.assertTrue(self.inside(text, T.CALL_ALONG), (players, nb, text))
            self.assertEqual(t["0"]["call"], ["", "", ""])                     # the big blind checks instead
            self.assertTrue(any(t["2"]["call"]))                              # the button may call along

    def test_facing_a_raise(self):
        T = self.T
        for players in T.TABLES:
            t = T.table(players)
            for key, row in t["vs_raise"].items():
                group, where = key.split("|")
                for hand in ("AA", "KK", "AKs"):
                    self.assertTrue(self.has(row["value"], hand), (players, key))
                self.assertFalse(self.has(row["value"], "76s"))
                if where == "bb":
                    self.assertGreater(sum(parse_range(row["call"])), 40, (players, key))
                if where == "sb":
                    self.assertLess(sum(parse_range(row["call"])) if row["call"] else 0, 8, (players, key))
            # a late raise is attacked with more hands than an early one
            first, last = T.groups(players)[0], "late"
            self.assertTrue(self.inside(t["vs_raise"][f"{first}|ip"]["value"], t["vs_raise"][f"{last}|ip"]["value"]))
            # the big blind's short-stack call rule stays inside what the engine allows
            for key, _label, _nb in self.B.raisers(players):
                allowed = [max(a, b) for a, b in zip(parse_range(t["bb_call"][key]),
                                                     parse_range(self.B.reshove("before", key, 20.0, players)))]
                for h, w in enumerate(parse_range(T.BB_CALL_SHORT)):
                    if w >= 0.5:
                        self.assertGreaterEqual(allowed[h], 0.5, (players, key, HANDS[h]))
            # a raise and a re-raise in front: the best hands only, fewer as stacks deepen
            for group, row in t["cold"].items():
                self.assertTrue(all(self.has(r, "AA") and self.has(r, "KK") for r in row), (players, group))
                self.assertTrue(self.inside(row[2], row[1]) and self.inside(row[1], row[0]), (players, group))
                self.assertFalse(self.has(row[0], "TT"))

    def test_after_raising(self):
        T = self.T
        for players in T.TABLES:
            t = T.table(players)
            for group, row in t["reraised"].items():
                self.assertTrue(self.has(row["allin"], "AA") and self.has(row["allin"], "KK"), (players, group))
                self.assertTrue(self.has(row["fourbet"], "AA"))
                self.assertFalse(self.has(row["allin"], "99"))
                # 45bb or less, the call list: hands that are too good to fold and whose all-in does not earn
                # enough (the final gate).  It shares no hand with the all-in list.
                self.assertTrue(self.inside(row["call_short"], "TT+, AQs+, AKo"), (players, group))
                self.assertFalse(any(self.has(row["allin"], hand) and self.has(row["call_short"], hand) for hand in HANDS),
                                 (players, group))
            self.assertIn(T.RERAISED_RULE, T.sheet_text(players))
        # under the gun with queens: all-in from a late seat, a call from the first seats (it was a fold)
        row = T.table(8)["reraised"]["early"]
        self.assertEqual((row["allin"], row["call_short"]), ("KK+, AKs", "QQ"))
        self.assertIn("you raised from UTG or UTG+1: 45bb or less all-in with KK+, AKs, call QQ; more than 45bb re-raise KK+",
                      T.sheet_text(8))
        self.assertEqual(self.answer(8, 7, 35.0, [(7, "raise", 2.2), (0, "raise", 8.4)], HAND_INDEX["QQ"]), "CALL")
        for players in T.TABLES:
            t = T.table(players)
            for group, rows in t["shoved_on"].items():
                opened = T.opened(players, group)
                for k in range(5):
                    self.assertTrue(self.inside(rows["bubble"][k], rows["normal"][k]), (players, group, k))
                    self.assertTrue(self.inside(rows["normal"][k], opened), (players, group, k))
                    self.assertTrue(self.has(rows["bubble"][k], "AA"))
                # a smaller all-in is called with more hands (bands run from small to big in the data)
                for a, b in zip(rows["normal"], rows["normal"][1:]):
                    self.assertTrue(self.inside(b, a), (players, group))
                self.assertEqual(T.over_raise(players, group, opened), "every hand you raised")

    def test_matches_the_engine(self):
        # the sheet is what the coach answers far from the money
        from poker_coach.icm import Prizes as P
        from poker_coach.preflop import Act, Spot
        T = self.T

        def action(players, hero_nb, stack, acts, hand):
            setup = HandSetup([float(stack)] * players, 0.5, 1.0, 0.0, players * 0.125)
            sp = Spot(setup=setup, hero=players - 1 - hero_nb, hand=HAND_INDEX[hand], prizes=P(), field_prizes=P())
            sp.acts = [Act(players - 1 - nb, kind, amount) for nb, kind, amount in acts]
            return advise(sp).action

        t = T.table(8)
        for hand in ("AQs", "T9s", "55", "KJo", "72o", "A5s"):
            got = action(8, 2, 60, [(4, "raise", 2.3)], hand)                 # button against a HJ raise
            row = t["vs_raise"]["middle|ip"]
            if self.has(row["value"], hand):
                self.assertTrue(got.startswith("3-BET"), (hand, got))
            elif self.has(row["bluff"], hand):
                self.assertIn("semi-bluff", got)
            elif any(self.has(row[k], hand) for k in ("call", "setmine", "button")):
                self.assertEqual(got, "CALL", hand)
            else:
                self.assertEqual(got, "FOLD", hand)
        for hand in ("AJo", "76s", "Q5o", "22"):
            got = action(8, 0, 40, [(4, "limp", 1.0)], hand)                   # big blind, one caller
            want = "RAISE" if self.has(t["limpers"]["0"]["raise"][0], hand) else "CHECK"
            self.assertTrue(got.startswith(want), (hand, got))
        for hand in ("KK", "QQ", "AKo", "JJ"):
            got = action(8, 0, 40, [(7, "raise", 2.2), (2, "raise", 6.6)], hand)   # a raise and a re-raise
            self.assertEqual("ALL-IN" in got, self.has(t["cold"]["early"][1], hand), (hand, got))

    @staticmethod
    def builder():
        """tools/build_tag.py as a module: the test goes through the data with the builder's own code."""
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location("build_tag", os.path.join(root, "tools", "build_tag.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def same_for(self, hands, stored, built, where):
        """Every range of ``stored`` (the data file) holds the same of ``hands`` as the freshly built one."""
        self.assertEqual(type(stored), type(built), where)
        if isinstance(stored, dict):
            self.assertEqual(set(stored), set(built), where)
            for key in stored:
                self.same_for(hands, stored[key], built[key], where + (key,))
        elif isinstance(stored, list):
            self.assertEqual(len(stored), len(built), where)
            for k, (a, b) in enumerate(zip(stored, built)):
                self.same_for(hands, a, b, where + (k,))
        elif isinstance(stored, str):
            for hand in hands:
                self.assertEqual(self.has(stored, HANDS[hand]), self.has(built, HANDS[hand]), where + (HANDS[hand],))
        else:
            self.assertEqual(stored, built, where)

    # ---- the engine asked directly, in the builder's setting ------------------------------------

    @staticmethod
    def answer(players, hero_nb, stack, acts, hand):
        """The engine's action: equal stacks, the table's ante on the big blind, chips only (as the builder asks)."""
        from poker_coach.icm import Prizes as P
        from poker_coach.preflop import Act, Spot
        setup = HandSetup([float(stack)] * players, 0.5, 1.0, 0.0, players * 0.125)
        sp = Spot(setup=setup, hero=players - 1 - hero_nb, hand=hand, prizes=P(), field_prizes=P())
        sp.acts = [Act(players - 1 - nb, kind, amount) for nb, kind, amount in acts]
        return advise(sp).action

    @staticmethod
    def kind_of(action: str) -> str:
        """An action as the list it belongs on: value (a re-raise or an all-in), bluff, call, raise or fold."""
        if "semi-bluff" in action:
            return "bluff"
        if action.startswith(("3-BET", "4-BET")) or "ALL-IN" in action:
            return "value"
        if action.startswith("RAISE"):
            return "raise"
        return {"CALL": "call", "FOLD": "fold", "CHECK": "fold"}.get(action, action)

    @staticmethod
    def weights(text: str) -> list:
        return parse_range(text) if text and text != "nothing" else [0.0] * 169

    RAISE_LISTS = ("value", "bluff", "call", "setmine", "button")       # the lists of a row of part 3
    # the hands part 4 (a raise and a re-raise) and part 5 (you were re-raised) are asked about here: every
    # hand on one of their lists, and the hands next to them
    PREMIUMS = "TT+, AQs+, AKo"
    STRONG = "22+, ATs+, KQs, AQo+"

    def raise_rows(self, players):
        """(key, row, hero's seat, [the seat the row is asked for, the other seats of its group], the raise)."""
        from poker_coach.ranges import open_size_bb
        build = self.builder()
        seats = dict(build.raiser_groups(players))
        for key, row in self.T.table(players)["vs_raise"].items():
            group, where = key.split("|")
            raisers = [seats[group]] + [int(nb) for nb in row["seats"]]
            yield key, row, {"ip": 2, "sb": 1, "bb": 0}[where], raisers, \
                lambda stack, nb, group=group: open_size_bb(stack, 1 if group == "sb" else nb)

    def no_hole_and_no_double_entry(self):
        """Every row of every part, at the stack it is asked at: a hand the engine plays is on exactly one
        list of its row, and a hand it folds is on none."""
        T = self.T
        stack = T.ASKED["vs_raise"]
        low, mid = T.CALL_FROM
        for players in T.TABLES:
            t = T.table(players)
            # part 3: one question with 60bb for every row, and for every seat of the raiser's group
            for key, row, h_nb, raisers, size in self.raise_rows(players):
                on = {name: self.weights(row.get(name, "")) for name in self.RAISE_LISTS}
                for nb in raisers:
                    other = row["seats"].get(str(nb), {})
                    more, less = self.weights(other.get("more", "")), self.weights(other.get("less", ""))
                    for h in range(169):
                        lists = [name for name in self.RAISE_LISTS if on[name][h] >= 0.5]
                        where = (players, key, f"raise from seat {nb}", HANDS[h], lists)
                        self.assertLessEqual(len(lists), 1, where)                        # no double entry
                        if less[h] >= 0.5:
                            self.assertEqual(lists, ["call"], where)                      # a call of the row ...
                            lists = []                                                    # ... not against this seat
                        if more[h] >= 0.5:
                            self.assertEqual(lists, [], where)
                            lists = ["call"]
                        got = self.kind_of(self.answer(players, h_nb, stack, [(nb, "raise", size(stack, nb))], h))
                        want = "fold" if not lists else "call" if lists[0] in ("call", "setmine", "button") else lists[0]
                        self.assertEqual(got, want, where)                                # no hole, nothing extra
                # ... and the calls are on the list of the stack they start at
                rep = raisers[0]
                for h in range(169):
                    name = next((n for n in ("call", "setmine", "button") if on[n][h] >= 0.5), None)
                    if name is None:
                        continue
                    at_low = self.answer(players, h_nb, low, [(rep, "raise", size(low, rep))], h)
                    at_mid = self.answer(players, h_nb, mid, [(rep, "raise", size(mid, rep))], h)
                    self.assertEqual((at_low == "CALL", at_mid == "CALL"),
                                     {"call": (True, True), "setmine": (False, True), "button": (False, False)}[name],
                                     (players, key, HANDS[h], name))
            # part 1: the raise lists against the engine at their two stacks.  With 50bb every hand; with 22bb
            # every hand that is not on the list (a hole would be there) and one that is (a raise costs the
            # engine two solved all-ins: the plan under it); the small blind solves its own all-in for every
            # hand up to 25bb, so it is asked about four hands.
            deep, short = T.ASKED["first_in"]
            for nb in T.seats(players):
                lists = [self.weights(text) for text in t["first_in"][str(nb)]["raise"]]
                for h in range(169):
                    got = self.kind_of(self.answer(players, nb, deep, [], h))
                    self.assertEqual(got, "raise" if lists[0][h] >= 0.5 else "fold", (players, nb, deep, HANDS[h]))
                listed = [h for h in range(169) if lists[1][h] >= 0.5]
                unlisted = [h for h in range(169) if lists[1][h] < 0.5]
                hands = unlisted + [listed[(7 * players + nb) % len(listed)]]
                if nb == 1:
                    hands = [listed[0], listed[-1], unlisted[0], unlisted[-1]]
                for h in hands:
                    got = self.kind_of(self.answer(players, nb, short, [], h))
                    self.assertEqual(got, "raise" if lists[1][h] >= 0.5 else "fold", (players, nb, short, HANDS[h]))
            # parts 2, 4 and 5: one question for each cell (the builder stops on an action no list takes, and
            # the cells are compared with it below); here the lists of one question share no hand
            for nb, row in t["limpers"].items():
                for k, text in enumerate(row["raise"]):
                    both = [HANDS[h] for h in range(169) if self.weights(text)[h] >= 0.5 and self.weights(row["call"][k])[h] >= 0.5]
                    self.assertEqual(both, [], (players, "limpers", nb, k))
            for group, row in t["reraised"].items():
                both = [HANDS[h] for h in range(169) if self.weights(row["fourbet"])[h] >= 0.5 and self.weights(row["call"])[h] >= 0.5]
                self.assertEqual(both, [], (players, "reraised", group))
                both = [HANDS[h] for h in range(169) if self.weights(row["allin"])[h] >= 0.5 and self.weights(row["call_short"])[h] >= 0.5]
                self.assertEqual(both, [], (players, "reraised", group, "45bb or less"))

    def test_l8_every_cell_is_what_the_builder_gets_from_the_engine(self):
        # tag.json against tools/build_tag.py, for 6, 7 and 8 players.  The cells that need no question to the
        # engine are compared whole.  "Players only called" and "a raise before you" are built again whole, with
        # all 169 hands.  "A raise and a re-raise" and "you raised and were re-raised" cost a solved all-in for
        # every hand: they are built again for the hands on their lists and the hands next to them.
        T, B, build = self.T, self.B, self.builder()
        premiums = [h for h in range(169) if parse_range(self.PREMIUMS)[h] >= 0.5]
        strong = [h for h in range(169) if parse_range(self.STRONG)[h] >= 0.5]
        try:
            for players in T.TABLES:
                t = T.table(players)
                b = B.table(players)
                self.assertEqual(t["first_in"], build.first_in(players), players)
                self.assertEqual(t["bb_call"], build.bb_call_short(players), players)
                self.assertEqual(t["shoved_on"], build.shoved_on(players), players)
                self.assertEqual(t["reshove"], {k: v[:4] for k, v in b["reshove"]["before"].items()}, players)
                self.assertEqual(t["call"], b["call"], players)
                build.HANDS_ASKED = list(range(169))
                self.assertEqual(t["limpers"], build.limpers(players), players)
                self.assertEqual(t["vs_raise"], build.vs_raise(players), players)
                for part, hands, make in (("cold", premiums, build.cold), ("reraised", strong, build.reraised)):
                    listed = [text for row in t[part].values() for text in (row if isinstance(row, list) else row.values())]
                    for text in listed:                           # (no hand of these lists goes unasked)
                        self.assertTrue(self.inside(text, self.PREMIUMS if part == "cold" else self.STRONG), (players, part, text))
                    build.HANDS_ASKED = hands
                    self.same_for(hands, t[part], make(players), (players, part))
        finally:
            build.HANDS_ASKED = list(range(169))
        # A hole or a double entry (E1): the builder cannot make one (a row is one question at one stack, and
        # ``place`` stops the build on an action no list takes), and the data file is asked again here.
        with self.assertRaises(RuntimeError):
            build.place({"call": [1.0] * 169}, {"play": ("allin", "reraise")}, "a call nobody lists")
        self.no_hole_and_no_double_entry()
        # ... and that check does fail on the hole that was found (KQs on no list of the big blind's row against
        # a late raise), on a double entry and on a hand the engine folds
        from unittest import mock
        late = T.table(6)["vs_raise"]["late|bb"]
        self.assertEqual(late["value"], "TT+, AJs+, KQs, AQo+")
        for name, text in (("value", "TT+, AJs+, AQo+"), ("call", late["call"] + ", KQs"), ("call", late["call"] + ", 72o")):
            broken = copy.deepcopy(T.data())
            broken["tables"]["6"]["vs_raise"]["late|bb"][name] = text
            with mock.patch.object(T, "data", lambda broken=broken: broken):
                with self.assertRaises(AssertionError, msg=(name, text)):
                    self.no_hole_and_no_double_entry()
        # the builder's other rules (L8): the big blind's short calls use the engine's points, ...
        from poker_coach.preflop import _hand_kind, bb_call_points
        from poker_coach.ranges import villain_open_range
        for players in T.TABLES:
            t = T.table(players)
            for key, _label, r_nb in B.raisers(players):
                opened = villain_open_range(r_nb, "unknown", 20.0)
                need = 1.0 / (players * B.PLAYER_ANTE + 0.5 + 1.0 + 2.0 + 1.0)
                all_in = parse_range(B.reshove("before", key, 20.0, players))
                calls = parse_range(t["bb_call"][key])
                for h in range(169):
                    price = eq_vs_range(h, opened)[0] - need - bb_call_points(_hand_kind(h)) >= 0
                    self.assertEqual(calls[h] >= 0.5, price and all_in[h] < 0.5, (players, key, HANDS[h]))
        # ... and the "you were re-raised" rows are asked with the big blind as the re-raiser
        self.assertIn("big blind as the player who re-raised", build.reraised.__doc__)

    def test_e1_every_row_of_the_sheet_is_one_question_at_one_stated_stack(self):
        # The hole that was found: KQs in the big blind against a raise from the cutoff or the button was on no
        # list at 6, 7 and 8 players (the re-raises were asked with 30bb, the big blind's calls with 60bb, and
        # KQs calls at one depth and re-raises at the other).  Now a row is one question with 60bb, the sheet
        # says so, and what it says about the other stacks is true.
        T = self.T
        hand = HAND_INDEX["KQs"]
        for players in T.TABLES:
            row = T.table(players)["vs_raise"]["late|bb"]
            self.assertEqual([name for name in self.RAISE_LISTS if self.has(row.get(name, ""), "KQs")], ["value"], players)
            for raiser in (3, 2):
                got = [self.answer(players, 0, stack, [(raiser, "raise", 2.2 if stack < 40 else 2.3)], hand) for stack in (30, 40, 60)]
                # never a fold: with 30 and 40bb a call (an all-in where that clearly earns), with 60bb a re-raise
                self.assertTrue(all(a in ("CALL", "ALL-IN") for a in got[:2]) and got[2].startswith("3-BET to"), (players, raiser, got))
            got = [self.answer(players, 0, stack, [(3, "raise", 2.2 if stack < 40 else 2.3)], hand) for stack in (30, 40)]
            self.assertEqual(got, ["CALL", "CALL"], players)                    # against the cutoff, as it was found
        # the stack of every list is in the sheet, and is the one the data was asked at
        for players in T.TABLES:
            text = T.sheet_text(players)
            for words in ("what the coach answers with 60bb to a raise of 2.3bb (3bb from the small blind)",
                          "on one list of the row", "what the coach answers with 50bb and with 22bb",
                          "what the coach answers with 40bb; in brackets, what changes with 20bb",
                          "answers in the big blind with 20bb, 40bb and 100bb",
                          "answers with 35bb and with 70bb to a re-raise from the big blind"):
                self.assertIn(words, text, players)
        self.assertEqual(T.ASKED, {"first_in": (50.0, 22.0), "limpers": (40.0, 20.0), "vs_raise": 60.0,
                                   "cold": (20.0, 40.0, 100.0), "reraised": (35.0, 70.0)})
        self.assertEqual(T.data()["version"], 3)

        def at(players, key, h_nb, raiser, size, eff, h, caller=None):
            """The engine's answer with ``eff`` big blinds effective (the big blind has posted the table's ante)."""
            stack = eff + (players * 0.125 if h_nb == 0 else 0.0)
            acts = [(raiser, "raise", size(stack, raiser))] + ([(caller, "call", size(stack, raiser))] if caller else [])
            return self.kind_of(self.answer(players, h_nb, stack, acts, h))

        # Part 3, the words under the rows, at other stacks than the row's (all rows at 8 players, the rows
        # that changed at 6 and 7).  A sample of each list: its best, its worst and one between.
        def some(text):
            hands = [h for h in range(169) if self.weights(text)[h] >= 0.5]
            return hands if len(hands) <= 3 else [hands[0], hands[len(hands) // 2], hands[-1]]

        for players in T.TABLES:
            for key, row, h_nb, raisers, size in self.raise_rows(players):
                if players != 8 and not key.startswith("late"):
                    continue
                rep, where = raisers[0], key.split("|")[1]
                for h in [h for h in range(169) if self.weights(row["value"])[h] >= 0.5]:
                    # more than 45bb: every hand on a re-raise list re-raises small
                    for eff in (46, 80):
                        self.assertEqual(at(players, key, h_nb, rep, size, eff, h), "value", (players, key, eff, HANDS[h]))
                    self.assertTrue(self.answer(players, h_nb, 80, [(rep, "raise", size(80, rep))], h).startswith("3-BET to"))
                    # 25 to 45bb: a small re-raise, an all-in or a call; a fold only in the small blind
                    for eff in (28, 40):
                        got = at(players, key, h_nb, rep, size, eff, h)
                        self.assertIn(got, ("value", "call", "fold") if where == "sb" else ("value", "call"), (players, key, eff, HANDS[h]))
                for h in some(row["bluff"]):
                    self.assertEqual(at(players, key, h_nb, rep, size, 46, h), "bluff", (players, key, HANDS[h]))
                    for eff in (28, 45):      # a bluff list folds; in the big blind it calls
                        self.assertEqual(at(players, key, h_nb, rep, size, eff, h), "call" if where == "bb" else "fold",
                                         (players, key, eff, HANDS[h]))
                for h in some(row["call"]):
                    for eff in (26, 36, 46, 100):
                        self.assertEqual(at(players, key, h_nb, rep, size, eff, h), "call", (players, key, eff, HANDS[h]))
                for h in some(row.get("setmine", "")):          # 15 times the raise: 33bb against 2.2bb
                    self.assertEqual([at(players, key, h_nb, rep, size, eff, h) for eff in (30, 35, 100)],
                                     ["fold", "call", "call"], (players, key, HANDS[h]))
                for h in some(row.get("button", "")):           # on the button or after a caller, 50bb or more
                    self.assertEqual([at(players, key, h_nb, rep, size, eff, h) for eff in (49, 50, 100)],
                                     ["fold", "call", "call"], (players, key, HANDS[h]))
                    if rep > 4:                                 # from the cutoff: only after a caller
                        self.assertEqual(at(players, key, 3, rep, size, 60, h), "fold", (players, key, HANDS[h]))
                        self.assertEqual(at(players, key, 3, rep, size, 60, h, caller=4), "call", (players, key, HANDS[h]))
        # the big blind calls by the price: a smaller raise, more hands; a bigger one, fewer; a caller, more
        calls = {}
        for raise_to, caller in ((2.0, None), (2.3, None), (3.0, None), (2.3, 2)):
            acts = [(3, "raise", raise_to)] + ([(caller, "call", raise_to)] if caller else [])
            calls[raise_to, caller] = {h for h in range(169) if self.answer(8, 0, 60, acts, h) == "CALL"}
        self.assertTrue(calls[3.0, None] < calls[2.3, None] < calls[2.0, None])
        self.assertTrue(calls[2.3, None] < calls[2.3, 2])
        self.assertEqual(calls[2.3, None], {h for h in range(169) if self.weights(T.table(8)["vs_raise"]["late|bb"]["call"])[h] >= 0.5})
        # the other seat of a group has its own line where the big blind's calls differ
        text = T.sheet_text(8)
        self.assertIn("if the raise came from LJ, do not call: K8o-K6o, Q9o, J9o, T9o", text)
        self.assertIn("if the raise came from BTN, call as well: K2o, Q7o-Q4o, J8o-J7o, T8o-T7o, 97o+, 87o", text)
        self.assertNotIn("if the raise came from UTG+1", text)             # (the same lists as against UTG)

        # Part 2: what a raise list loses with 17 to 24bb is in brackets, taken from the data
        limpers = T.table(8)["limpers"]
        self.assertEqual(T.short_stack_note(limpers["3"], 0), " (17 to 24bb: without T8s, 98s, 87s, 76s)")   # the cutoff
        self.assertEqual(T.short_stack_note(limpers["6"], 0), " (17 to 24bb: without T9s)")                  # UTG+1
        self.assertEqual(T.short_stack_note(limpers["2"], 0), "")                                            # the button
        self.assertNotIn("without the suited connectors below T9s", text)
        self.assertIn("three callers", text)
        self.assertNotIn("three or more", text)
        for nb, row in limpers.items():
            for k in range(len(row["raise"])):
                self.assertTrue(self.inside(row["mid"][k], row["raise"][k]), (nb, k))
        # ... with 20bb nobody calls along, and with four callers the list shrinks again, never below the floor
        acts = [(3, "limp", 1.0)]
        self.assertEqual(self.answer(8, 2, 40, acts, HAND_INDEX["54s"]), "CALL (limp behind)")
        self.assertEqual(self.answer(8, 2, 20, acts, HAND_INDEX["54s"]), "FOLD")
        four = [(nb, "limp", 1.0) for nb in (7, 6, 5, 4)]
        three_callers = T.table(8)["limpers"]["0"]["raise"][2]
        for name in ("AA", "99", "AJs", "AQo", "KQs", "55", "98s", "66", "T9s", "72o"):
            raised = self.answer(8, 0, 40, four, HAND_INDEX[name]).startswith("RAISE")
            if self.has(T.ALWAYS_OVER_CALLERS, name):
                self.assertTrue(raised, name)
            if raised:
                self.assertTrue(self.has(three_callers, name), name)
        self.assertFalse(self.answer(8, 0, 40, four, HAND_INDEX["55"]).startswith("RAISE"))    # (55 is raised behind three)
        self.assertTrue(self.has(three_callers, "55"))

    def test_g_e2_the_big_blinds_calls_say_the_ante_they_are_priced_with(self):
        # Found at the gate: the sheet says "each row is what the coach answers with 60bb", and at six and seven
        # players `quick` called 27 hands in the big blind that the rows fold (six players, a hijack raise: Q9o,
        # J9o, T9o, K7o, K6o).  The rows are asked with an ante of an eighth of a big blind a player (0.75bb at
        # six players, what a tracked table with 300/600/75 has); `quick` always posts a 1bb big-blind ante, and
        # the big blind calls by the price.  At eight players the two are the same bet.  The sheet says the ante.
        T = self.T
        hand = HAND_INDEX["Q9o"]
        row = T.table(6)["vs_raise"]["middle|bb"]                          # six players, the hijack raises
        self.assertEqual([name for name in self.RAISE_LISTS if self.has(row.get(name, ""), "Q9o")], [])
        self.assertEqual(self.answer(6, 0, 60, [(4, "raise", 2.3)], hand), "FOLD")             # the sheet's ante
        each = HandSetup([60.0] * 6, 0.5, 1.0, 0.125, 0.0)                 # ... also when every player posts it
        spot = quick_spot(hand, None, 60, 6, "BB", "HJ raise 2.3bb")
        self.assertEqual(spot.setup.antes, [0.0] * 5 + [1.0])              # what `quick` posts at every table size
        self.assertEqual(advise(spot).action, "CALL")
        spot.setup = each
        self.assertEqual(advise(spot).action, "FOLD")
        for players, ante in ((6, "0.75bb"), (7, "0.875bb"), (8, "1bb")):
            text = T.sheet_text(players)
            self.assertIn("The big blind calls by the price", text)
            self.assertIn(f"The price counts an ante of an eighth of a big blind from each player ({ante} in all at "
                          "this table); with a bigger ante it calls a few more hands.", text)
        # eight players: the same ante, the same answers (the hands on either side of the row's last calls)
        row = T.table(8)["vs_raise"]["middle|bb"]
        for name in ("Q9o", "Q8o", "K6o", "K5o", "T9o", "T8o"):
            on = any(self.has(row.get(key, ""), name) for key in self.RAISE_LISTS)
            quick = advise(quick_spot(HAND_INDEX[name], None, 60, 8, "BB", "HJ raise 2.3bb")).action
            self.assertEqual(quick != "FOLD", on, name)
            self.assertEqual(quick, self.answer(8, 0, 60, [(4, "raise", 2.3)], HAND_INDEX[name]), name)

    def test_e2_the_second_re_raise_is_said_the_way_the_engine_makes_it(self):
        # The sheet's own sentences disagreed: "Second re-raise ... with more than 60bb" (the sizes) and "more
        # than 45bb: re-raise KK+" (part 5).  The engine does both, in two different spots:
        # your own raise was re-raised: a small second re-raise with more than 45bb, all-in with less; ...
        T = self.T
        kings = HAND_INDEX["KK"]
        reraised = [(3, "raise", 2.2), (0, "raise", 8.4)]                  # the cutoff raises, the big blind re-raises
        for stack, want in ((46, "ALL-IN"), (47, "4-BET to 19bb"), (61, "4-BET to 19bb"), (100, "4-BET to 19bb")):
            self.assertEqual(self.answer(8, 3, stack, reraised, kings), want, stack)      # (the big blind has 1bb less)
        # ... a raise and a re-raise came before you: all-in up to 60bb, a small re-raise with more
        cold = [(7, "raise", 2.2), (4, "raise", 6.6)]                      # under the gun raises, the hijack re-raises
        for stack, want in ((40, "ALL-IN"), (60, "ALL-IN"), (61, "4-BET to 15bb"), (100, "4-BET to 15bb")):
            self.assertEqual(self.answer(8, 2, stack, cold, kings), want, stack)
        sizes = dict(T.SIZES)["Second re-raise"]
        self.assertIn("2.3 times their re-raise", sizes)                   # 2.3 x 8.4 = 19bb, 2.3 x 6.6 = 15bb
        self.assertIn("Your own raise was re-raised: with more than 45bb", sizes)
        self.assertIn("A raise and a re-raise came before you: with more than 60bb", sizes)
        self.assertIn("With less, all-in", sizes)
        self.assertNotIn("re-raise with more than 60bb. With less", sizes)
        text = T.sheet_text(8)
        self.assertIn("Second re-raise: " + sizes, text)
        self.assertIn("A raise and a re-raise before you: all-in (re-raise with more than 60bb) with", text)      # part 4
        self.assertIn("45bb or less all-in with TT+, AQs+, AKo; more than 45bb re-raise KK+", text)              # part 5

    def test_sheet_cli_and_playbook(self):
        import io
        import os
        from contextlib import redirect_stderr, redirect_stdout
        from poker_coach.cli import main
        T = self.T
        for players in T.TABLES:
            text = T.sheet_text(players)
            for part in ("1. NOBODY HAS ENTERED", "2. PLAYERS ONLY CALLED", "3. A RAISE BEFORE YOU, 25BB OR MORE",
                         "4. A RAISE BEFORE YOU, 24BB OR LESS", "5. YOU RAISED FIRST", "6. AN ALL-IN BEFORE YOU", "7. THE PLAN",
                         "otherwise: check", "every hand you raised", T.CALL_ALONG, T.BB_CALL_WORDS):
                self.assertIn(part, text, (players, part))
            self.assertNotIn("(nothing)", text)
            self.assertEqual("UTG+1" in text, players == 8)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["tag-sheet", "--players", "7"]), 0)
        self.assertIn("SHEET, 7 PLAYERS", out.getvalue())
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertNotEqual(main(["tag-sheet", "--players", "9"]), 0)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "PLAYBOOK.md")) as fh:
            book = fh.read()
        for text in (T.CALL_ALONG, T.BB_CALL_WORDS, "tag-sheet"):
            self.assertIn(text, book)
        for group, row in T.table(8)["reraised"].items():
            self.assertIn(row["allin"], book, group)
        for group, row in T.table(8)["cold"].items():
            for text in row:
                self.assertIn(text, book, group)


def _has(module: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(module) is not None


@unittest.skipUnless(_has("pydantic"), "the live reader needs pydantic (pip install -r requirements-live.txt)")
class LiveReader(unittest.TestCase):
    """The live table reader (poker_coach/live): readings -> suggestions, the play-money check, the loop."""

    BASE = {"money_text": "Play Money", "table_text": "PM Turbo 100/200 Ante 25", "small_blind": 100,
            "big_blind": 200, "ante": 25, "ante_kind": "per_player", "hero_to_act": True}

    @staticmethod
    def seats(spec):
        out = []
        for name, stack, bet, flags in spec:
            d = {"name": name, "stack": stack, "bet": bet}
            for f in flags.split():
                d[f] = True
            out.append(d)
        return out

    def read(self, cards, spec, **extra):
        from poker_coach.live.schema import table_from_dict
        return table_from_dict({**self.BASE, "hero_cards": cards, "seats": self.seats(spec), **extra})

    def btn_first_in(self, cards):
        return self.read(cards, [("Hero", 5000, 0, "is_hero has_button"), ("Ann", 4900, 100, ""),
                                 ("Bob", 6000, 200, ""), ("Cat", 4000, 0, "folded"),
                                 ("Dan", 7000, 0, "folded"), ("Eve", 3000, 0, "folded")])

    def test_play_money_check(self):
        from poker_coach.live.decide import LiveSettings, play_money_check, suggest
        r = self.btn_first_in(["Ah", "Jd"])
        self.assertTrue(play_money_check(r)[0])
        real = r.model_copy(update={"money_text": "$5.40", "table_text": "Bounty Hunters $5.40"})
        ok, why = play_money_check(real)
        self.assertFalse(ok)
        self.assertIn("$5.40", why)
        sug = suggest(real, LiveSettings())
        self.assertEqual(sug.kind, "blocked")
        self.assertEqual(sug.action, "")
        # a client that marks play money differently: the user adds its words
        pm = real.model_copy(update={"money_text": "", "table_text": "Fun Table 7"})
        self.assertFalse(play_money_check(pm)[0])
        self.assertTrue(play_money_check(pm, ("fun table",))[0])
        self.assertEqual(suggest(r.model_copy(update={"is_poker_table": False}), LiveSettings()).kind, "wait")

    def test_preflop(self):
        from poker_coach.live.decide import LiveSettings, suggest
        tag = LiveSettings()
        s = suggest(self.btn_first_in(["Ah", "Jd"]), tag)
        self.assertEqual(s.kind, "act")
        self.assertTrue(s.action.startswith("RAISE to 2.2bb"), s.action)
        self.assertIn("(440)", s.action)                     # the chip amount next to the big blinds
        self.assertIn("BTN", s.info)
        self.assertTrue(suggest(self.btn_first_in(["7c", "2d"]), tag).action.startswith("FOLD"))
        # not hero's turn: no suggestion unless asked
        wait = self.btn_first_in(["Ah", "Jd"]).model_copy(update={"hero_to_act": False})
        self.assertEqual(suggest(wait, tag).kind, "wait")
        self.assertEqual(suggest(wait, tag, force=True).kind, "act")
        # big blind, a raise from the first seat, 20bb effective: queens move in
        bb_vs = self.read(["Qs", "Qc"], [("Hero", 4800, 200, "is_hero"), ("Cat", 3560, 440, ""),
                                         ("Dan", 7000, 0, "folded"), ("Eve", 3000, 0, "folded has_button"),
                                         ("Ann", 4900, 100, "folded")])
        self.assertEqual(suggest(bb_vs, tag).action, "ALL-IN")
        self.assertEqual(suggest(bb_vs, LiveSettings(mode="binary")).action, "ALL-IN")
        trash = bb_vs.model_copy(update={"hero_cards": ["9c", "4d"]})
        self.assertEqual(suggest(trash, LiveSettings(mode="binary")).action, "FOLD")
        # big blind, one limper: check, never fold
        limp = self.read(["7c", "2d"], [("Hero", 4800, 200, "is_hero"), ("Cat", 4000, 0, "folded"),
                                        ("Dan", 6800, 200, ""), ("Eve", 3000, 0, "folded has_button"),
                                        ("Ann", 4900, 100, "folded")])
        self.assertEqual(suggest(limp, tag).action, "CHECK")

    def test_spin_mode(self):
        from poker_coach.live.decide import LiveSettings, suggest
        from poker_coach.live.schema import table_from_dict
        spin = LiveSettings(mode="spin")

        def r(cards, spec):
            return table_from_dict({"money_text": "Play Money", "small_blind": 10, "big_blind": 20, "hero_to_act": True,
                                    "hero_cards": cards, "seats": self.seats(spec)})
        # small blind against a 10bb all-in from the button: the effective stack is the all-in
        allin = [("Hero", 290, 10, "is_hero"), ("Bob", 280, 20, ""), ("Cat", 0, 200, "has_button all_in")]
        s = suggest(r(["As", "5d"], allin), spin)
        self.assertEqual(s.action, "FOLD")
        self.assertIn("10bb effective", s.reason)
        self.assertEqual(suggest(r(["Ks", "Kd"], allin), spin).action, "CALL")
        # big blind, nobody raised: check
        walk = [("Hero", 280, 20, "is_hero"), ("Cat", 300, 0, "folded has_button"), ("Bob", 290, 20, "")]
        self.assertEqual(suggest(r(["7c", "2d"], walk), spin).action, "CHECK")
        self.assertEqual(suggest(self.btn_first_in(["Ah", "Jd"]), spin).kind, "error")   # 6 players

    def test_actions_from_bets(self):
        from poker_coach import state as S
        from poker_coach.live.decide import LiveSettings, preflop_acts, to_table
        r = self.read(["Ah", "Kd"], [("Hero", 4400, 600, "is_hero has_button"), ("Ann", 4900, 100, "folded"),
                                     ("Bob", 3200, 1800, ""), ("Cat", 3800, 200, ""), ("Dan", 0, 3000, "all_in"),
                                     ("Eve", 3000, 0, "folded")])
        t = to_table(r, LiveSettings())
        order = S.action_order(t.state)
        acts = preflop_acts(t, order)
        got = [(order[a.idx], a.kind, a.amount) for a in acts]
        # Cat limped (200), hero raised to 600, Bob re-raised to 1800, Dan all-in for 3000
        self.assertEqual(got, [(4, "limp", 200.0), (1, "raise", 600.0), (3, "raise", 1800.0), (5, "allin", 3000.0)])
        # start-of-hand stacks put the chips in front and the ante back
        self.assertEqual(S.seats(t.state)["1"]["stack"], 4400 + 600 + 25)

    def test_button_units_and_warnings(self):
        from poker_coach.live.decide import LiveSettings, to_table
        r = self.read(["Ah", "Jd"], [("Hero", 5000, 0, "is_hero"), ("Ann", 4900, 100, ""), ("Bob", None, 200, ""),
                                     ("Cat", 4000, 0, "folded")])
        t = to_table(r, LiveSettings())
        self.assertEqual(t.button, 1)                          # placed from the blinds in front
        self.assertTrue(any("button" in w for w in t.warnings))
        self.assertTrue(any("Bob" in w for w in t.warnings))   # the unreadable stack is named
        inbb = self.read(["Ah", "Jd"], [("Hero", 25, 0, "is_hero has_button"), ("Ann", 24.5, 0.5, ""),
                                        ("Bob", 30, 1, "")], amounts_in_bb=True, ante=None, ante_kind="none")
        t = to_table(inbb, LiveSettings())
        self.assertEqual((t.sb, t.bb, t.unit), (0.5, 1.0, "bb"))
        with self.assertRaises(ValueError):
            to_table(self.read(["Ah", "Jd"], [("Hero", 5000, 0, "is_hero"), ("Ann", 4900, 0, "")]), LiveSettings())

    def test_postflop(self):
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        tag = LiveSettings()
        mem = HandMemory()
        first = self.btn_first_in(["Ah", "Jd"])
        mem.update(first, suggest(first, tag))
        self.assertTrue(mem.hero_raised)
        flop = self.read(["Ah", "Jd"], [("Hero", 4540, 0, "is_hero has_button"), ("Ann", 4900, 0, "folded"),
                                        ("Bob", 5140, 400, ""), ("Cat", 4000, 0, "folded"),
                                        ("Dan", 7000, 0, "folded"), ("Eve", 3000, 0, "folded")],
                         board=["Kd", "7c", "2s"], middle_pot=1100)
        s = suggest(flop, tag, mem)
        self.assertEqual(s.kind, "act")
        self.assertIn("pot 7.5bb", s.info)                      # 1,100 in the middle and the 400 bet
        self.assertIn("to call 2.0bb", s.info)
        self.assertFalse(any("preflop action not seen" in w for w in s.warnings))
        alone = suggest(flop, tag)                              # no memory: opponents read as callers
        self.assertTrue(any("preflop action not seen" in w for w in alone.warnings))
        checked = flop.model_copy(update={"seats": [x.model_copy(update={"bet": 0.0}) for x in flop.seats],
                                          "middle_pot": 1100})
        c = suggest(checked, tag, mem)
        self.assertIn("checked to you", c.info)
        self.assertTrue(c.action.split()[0] in ("BET", "CHECK"), c.action)

    @unittest.skipUnless(_has("PIL"), "needs Pillow")
    def test_watchers(self):
        from PIL import Image, ImageDraw
        from poker_coach.live.capture import ButtonWatch, ChangeWatch, Rect, difference, thumb

        def frame(turn, shade=90):
            img = Image.new("RGB", (800, 560), (20, shade, 40))
            if turn:
                ImageDraw.Draw(img).rectangle((520, 480, 790, 550), fill=(220, 60, 60))
            return img
        area = Rect(500, 470, 300, 90)
        bw = ButtonWatch(area, thumb(frame(False).crop(area.box())))
        fired = [bw.update(f) for f in [frame(False)] * 2 + [frame(True)] * 3 + [frame(False), frame(True)]]
        self.assertEqual(fired, [False, False, True, False, False, False, True])
        cw = ChangeWatch(min_gap=2.0)
        t = 1000.0
        self.assertFalse(cw.update(frame(False), t))            # first frame: not settled yet
        self.assertTrue(cw.update(frame(False), t + 0.3))       # settled and new
        self.assertFalse(cw.update(frame(False), t + 3.0))      # nothing changed
        self.assertFalse(cw.update(frame(False, 160), t + 3.3)) # moving
        self.assertTrue(cw.update(frame(False, 160), t + 3.6))  # settled again, changed
        self.assertFalse(cw.update(frame(False, 30), t + 3.7) or cw.update(frame(False, 30), t + 3.8))  # too soon
        self.assertEqual(difference(None, [1]), 255.0)
        self.assertEqual(Rect.parse("1,2,3,4").box(), (1, 2, 4, 6))
        with self.assertRaises(ValueError):
            Rect.parse("1,2,3")

    @unittest.skipUnless(_has("PIL"), "needs Pillow")
    def test_worker_reads_once_per_turn(self):
        import queue
        import tempfile
        import time as _t
        from PIL import Image, ImageDraw
        from poker_coach.live import app
        from poker_coach.live.capture import Rect, thumb
        from poker_coach.live.reader import ReadResult

        def frame(turn):
            img = Image.new("RGB", (800, 560), (20, 90, 40))
            if turn:
                ImageDraw.Draw(img).rectangle((520, 480, 790, 550), fill=(220, 60, 60))
            return img
        frames = [frame(False)] * 3 + [frame(True)] * 5 + [frame(False)] * 3 + [frame(True)] * 30
        reading = self.btn_first_in(["Ah", "Jd"])

        class Grab:
            k = 0

            def grab(self):
                Grab.k += 1
                return frames[min(Grab.k - 1, len(frames) - 1)]

        class Reader:
            calls = 0

            def read(self, _img):
                Reader.calls += 1
                return ReadResult(reading, 1.2, 2600, 700, 0.0244, "claude-opus-5-5")

        area = Rect(500, 470, 300, 90)
        cfg = app.LiveConfig(region=[0, 0, 800, 560], buttons=area.as_list(),
                             baseline=thumb(frame(False).crop(area.box())), save_images=True)
        out = queue.Queue()
        with tempfile.TemporaryDirectory() as tmp:
            old = app.LOG_ROOT
            app.LOG_ROOT = tmp
            try:
                w = app.Worker(cfg, out, reader=Reader(), grabber=Grab(), poll=0.005)
                w.start()
                deadline = _t.time() + 5
                while Reader.calls < 2 and _t.time() < deadline:
                    _t.sleep(0.02)
                _t.sleep(0.2)
                w.stopped.set()
                w.join(2)
            finally:
                app.LOG_ROOT = old
            self.assertEqual(Reader.calls, 2)
            ups = [out.get() for _ in range(out.qsize())]
            sugs = [u for u in ups if u.suggestion is not None]
            self.assertEqual(len(sugs), 2)
            self.assertTrue(sugs[0].suggestion.action.startswith("RAISE"))
            self.assertAlmostEqual(sugs[1].session_cost, 0.0488)
            logs = os.listdir(tmp)
            self.assertEqual(len(logs), 1)
            files = os.listdir(os.path.join(tmp, logs[0]))
            self.assertIn("reads.jsonl", files)
            self.assertIn("0001.png", files)
            with open(os.path.join(tmp, logs[0], "reads.jsonl")) as fh:
                first = json.loads(fh.readline())
            self.assertEqual(first["reading"]["hero_cards"], ["Ah", "Jd"])
            self.assertTrue(first["suggestion"]["action"].startswith("RAISE"))

    @unittest.skipUnless(_has("anthropic") and _has("PIL"), "needs the anthropic SDK and Pillow")
    def test_reader_request(self):
        import anthropic
        from PIL import Image
        from poker_coach.live.reader import ClaudeReader, ReadError, encode_image
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx
        reply = self.btn_first_in(["Ah", "Jd"]).model_dump()
        seen = {}

        def ok(request):
            seen["body"] = json.loads(request.content)
            seen["beta"] = request.headers.get("anthropic-beta")
            return httpx.Response(200, json={
                "id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": json.dumps(reply)}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 2600, "output_tokens": 700}})

        client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(ok)))
        res = ClaudeReader(client=client).read(Image.new("RGB", (3200, 2000)))
        body = seen["body"]
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(seen["beta"], "server-side-fallback-2026-07-01")
        self.assertEqual(body["output_config"]["effort"], "low")
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertIn("seats", body["output_config"]["format"]["schema"]["required"])
        self.assertEqual(body["messages"][0]["content"][0]["source"]["media_type"], "image/png")
        self.assertEqual(res.table.hero_cards, ["Ah", "Jd"])
        self.assertAlmostEqual(res.cost, (2600 * 4 + 700 * 20) / 1e6)
        ClaudeReader(model="claude-haiku-5-5", client=client).read(Image.new("RGB", (200, 100)))
        self.assertNotIn("fallbacks", seen["body"])            # Haiku takes no server-side fallback
        # the image sent is cut down to the long edge
        import base64
        import io
        img = Image.open(io.BytesIO(base64.b64decode(encode_image(Image.new("RGB", (3200, 2000)), 1600))))
        self.assertEqual(img.size, (1600, 1000))

        def refuse(request):
            return httpx.Response(200, json={"id": "m", "type": "message", "role": "assistant",
                                             "model": "claude-opus-5-5", "content": [], "stop_reason": "refusal",
                                             "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}})
        c2 = anthropic.Anthropic(api_key="t", http_client=httpx.Client(transport=httpx.MockTransport(refuse)))
        with self.assertRaises(ReadError):
            ClaudeReader(client=c2).read(Image.new("RGB", (100, 100)))

    def test_cli(self):
        import tempfile
        from poker_coach.live.decide import DEFAULT_MARKERS
        reading = {**self.BASE, "hero_cards": ["Ah", "Jd"],
                   "seats": self.seats([("Hero", 5000, 0, "is_hero has_button"), ("Ann", 4900, 100, ""),
                                        ("Bob", 6000, 200, "")])}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.json")
            with open(path, "w") as fh:
                json.dump(reading, fh)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["live-test", "--json", path]), 0)
            self.assertIn(">>> RAISE", out.getvalue())
            self.assertIn("seats (clockwise from you)", out.getvalue())
            reading["money_text"], reading["table_text"] = "$11", "Sunday $11"
            with open(path, "w") as fh:
                json.dump(reading, fh)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["live-test", "--json", path]), 0)
            self.assertIn("[blocked]", out.getvalue())
            self.assertNotIn(">>>", out.getvalue())
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertNotEqual(main(["live-test"]), 0)
        self.assertIn("play money", DEFAULT_MARKERS)


import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # tests/fake_table.py


@unittest.skipUnless(_has("pydantic") and _has("PIL"), "the local reader needs pydantic and Pillow "
                     "(pip install -r requirements-live.txt)")
class LocalTableReader(unittest.TestCase):
    """The local reader (live/local.py, live/vision.py): taught on a drawn table, then reading new ones."""

    SETUP = {"seats": [{"stack": 5000}, {"stack": 4900, "bet": 100}, {"stack": 6000, "bet": 200},
                       {"stack": 4000}, {"stack": 7000}, {"stack": 3000}], "button": 0, "hero": ["Ah", "Kd"],
             "board": ["Qs", "Jc", "Th", "9d", "8s"], "pot": 375, "turn": False}

    @classmethod
    def setUpClass(cls):
        from fake_table import layout_for, render, truth
        from poker_coach.live.capture import Rect, thumb
        from poker_coach.live.local import learn, teach_items
        from poker_coach.live.vision import Book

        img, cls.boxes = render(cls.SETUP)
        cls.layout = layout_for(img, cls.boxes)
        cls.baseline = thumb(img.crop(Rect(*cls.boxes["buttons"]).box()))
        cls.book = Book()
        cls.first_questions = len(teach_items(img, cls.layout, cls.book))
        for it in teach_items(img, cls.layout, cls.book, everything=True):
            assert learn(cls.book, it, truth(cls.SETUP, it.name)) == "", it.name
        rng = random.Random(3)
        for _ in range(12):                      # a few hands later: label what is still unknown
            spec = cls.random_spec(rng)
            for it in teach_items(render(spec)[0], cls.layout, cls.book):
                assert learn(cls.book, it, truth(spec, it.name)) == "", it.name

    @staticmethod
    def random_spec(rng, turn=True):
        deck = [r + s for r in "23456789TJQKA" for s in "shdc"]
        rng.shuffle(deck)
        seats = [{"stack": rng.choice([rng.randint(800, 99999), rng.randint(100, 9999)]),
                  "bet": rng.choice([0, 0, rng.randint(50, 4000)]), "cards": rng.random() < 0.7} for _ in range(6)]
        return {"seats": seats, "button": rng.randrange(6), "hero": deck[:2],
                "board": deck[2:2 + rng.choice([0, 3, 4, 5])], "pot": rng.randint(100, 50000), "turn": turn}

    def reader(self):
        from poker_coach.live.local import LocalReader
        return LocalReader(self.layout, self.book, self.boxes["buttons"], self.baseline)

    def test_everything_is_asked_first(self):
        self.assertGreaterEqual(self.first_questions, 10)       # an empty book knows nothing
        for c in "0123456789,":
            self.assertIn(c, self.book.glyphs.chars)
        self.assertEqual(set(self.book.cards.suits), set("shdc"))

    def test_reads_new_tables(self):
        from fake_table import render
        reader = self.reader()
        rng = random.Random(100)
        for i in range(15):
            spec = self.random_spec(rng, turn=(i % 4 != 0))
            t = reader.read(render(spec)[0]).table
            self.assertEqual(t.hero_cards, spec["hero"])
            self.assertEqual(t.board, spec["board"])
            self.assertEqual(t.hero_to_act, spec["turn"])
            self.assertEqual([s.stack for s in t.seats], [s["stack"] for s in spec["seats"]])
            self.assertEqual([s.bet for s in t.seats], [s["bet"] for s in spec["seats"]])
            self.assertEqual([k for k, s in enumerate(t.seats) if s.has_button], [spec["button"]])
            self.assertEqual([s.folded for s in t.seats[1:]], [not s["cards"] for s in spec["seats"][1:]])
            self.assertEqual(t.total_pot, spec["pot"])
            self.assertEqual(t.money_text, "PLAY MONEY")
            self.assertEqual(t.unreadable, "")

    def test_suggests_from_a_reading(self):
        from fake_table import render
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        spec = {"seats": [{"stack": 5000}, {"stack": 4900, "bet": 100}, {"stack": 6000, "bet": 200},
                          {"stack": 4000, "cards": False}, {"stack": 7000, "cards": False},
                          {"stack": 3000, "cards": False}], "button": 0, "hero": ["Ah", "Jd"], "pot": 375}
        r = self.reader().read(render(spec)[0]).table
        self.assertEqual((r.small_blind, r.big_blind), (100, 200))
        self.assertEqual(r.ante_kind, "per_player")
        sug = suggest(r, LiveSettings(), HandMemory())
        self.assertEqual(sug.kind, "act")
        self.assertTrue(sug.action.startswith("RAISE"), sug.text())

    def test_unknown_is_asked_not_guessed(self):
        from fake_table import render
        from poker_coach.live.local import LocalReader, teach_items
        from poker_coach.live.vision import Book
        img = render(self.SETUP)[0]
        fresh = LocalReader(self.layout, Book()).read(img).table
        self.assertEqual(fresh.hero_cards, [])
        self.assertIn("not learned yet", fresh.unreadable)
        self.assertTrue(all(s.stack is None for s in fresh.seats))
        names = [it.name for it in teach_items(img, self.layout, Book())]
        self.assertIn("your card 1", names)
        self.assertIn("seat 3 bet", names)

    def test_play_money_marker_required(self):
        from fake_table import render
        from poker_coach.live.decide import DEFAULT_MARKERS, LiveSettings, suggest
        from poker_coach.live.wizard import marker_ok
        img = render(dict(self.SETUP, board=[], marker=False))[0]
        r = self.reader().read(img).table
        self.assertNotIn("money", r.money_text.lower())
        self.assertEqual(suggest(r, LiveSettings()).kind, "blocked")
        self.assertTrue(marker_ok("PLAY MONEY", DEFAULT_MARKERS))
        self.assertFalse(marker_ok("Bounty $5.40", DEFAULT_MARKERS))
        lay = copy.deepcopy(self.layout)
        lay.marker_text = ""
        self.assertIn("the play-money marker", lay.problems())

    def test_size_change_and_learning_errors(self):
        from fake_table import render
        from poker_coach.live.local import PIECES, TeachItem, learn
        from poker_coach.live.reader import ReadError
        from poker_coach.live.vision import Book
        img = render(self.SETUP)[0]
        with self.assertRaises(ReadError):
            self.reader().read(img.resize((800, 533)))
        crop = img.crop((self.boxes["seats"][0]["stack"][0], self.boxes["seats"][0]["stack"][1],
                         self.boxes["seats"][0]["stack"][0] + 120, self.boxes["seats"][0]["stack"][1] + 26))
        book = Book()
        # four characters typed for five pieces: label the pieces one by one instead
        self.assertEqual(learn(book, TeachItem("text", "your stack", crop), "5000"), PIECES)
        self.assertEqual(learn(book, TeachItem("text", "your stack", crop), "5,000"), "")
        self.assertEqual(book.glyphs.read(crop), "5,000")
        self.assertEqual(learn(book, TeachItem("text", "x", crop), "  "), "skipped")

    def test_files_round_trip(self):
        from poker_coach.live.local import Layout
        from poker_coach.live.vision import Book
        with tempfile.TemporaryDirectory() as d:
            self.layout.save(os.path.join(d, "layout.json"))
            self.book.save(os.path.join(d, "book.json"))
            lay, book = Layout.load(os.path.join(d, "layout.json")), Book.load(os.path.join(d, "book.json"))
        self.assertEqual(lay, self.layout)
        self.assertEqual(lay.problems(), [])
        self.assertEqual(book.summary(), self.book.summary())

    def test_amounts(self):
        from poker_coach.live.vision import parse_amount, word_of
        for text, value in (("12,450", 12450), ("Pot: 1,250", 1250), ("1.5K", 1500), ("2M", 2e6),
                            ("1.250", 1250), ("Pot: 3,4?0", None), ("12.5", 12.5)):
            self.assertEqual(parse_amount(text), value, text)
        self.assertEqual(word_of("All-in"), "all-in")
        self.assertEqual(word_of("Sitting Out"), "away")


@unittest.skipUnless(_has("pydantic") and _has("PIL"), "the local reader needs pydantic and Pillow "
                     "(pip install -r requirements-live.txt)")
class LocalCoach(LocalTableReader):
    """The whole chain on a drawn table: reading -> position, stack, the action in front -> advice,
    followed through a hand, and what happens when something cannot be read."""

    BOARD = ["Ks", "7d", "2c"]

    @staticmethod
    def spot(stacks, bets, cards, **extra):
        seats = [{"stack": s, "bet": b, "cards": c} for s, b, c in zip(stacks, bets, cards)]
        return dict({"seats": seats, "button": 1, "hero": ["Ah", "Kd"]}, **extra)

    def see(self, reader, spec):
        from fake_table import render
        return reader.read(render(spec)[0])

    # the button is seat 2: seat 3 small blind, seat 4 big blind, seat 5 first to act, hero in the cutoff
    IN = [True] * 6
    RAISED = ([4975, 4975, 4875, 4775, 4475, 4975], [0, 0, 100, 200, 500, 0])

    def test_position_stack_and_action_in_front(self):
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        reader = self.reader()
        res = self.see(reader, self.spot(*self.RAISED, [True, True, True, True, True, False], pot=950))
        self.assertEqual((res.table.small_blind, res.table.big_blind, res.table.ante_kind), (100, 200, "per_player"))
        sug = suggest(res.table, LiveSettings(), HandMemory(), blocking=res.blocking)
        self.assertEqual(sug.kind, "act")
        for part in ("AKo", "CO", "25bb", "6 players", "raises to 2.5bb"):
            self.assertIn(part, sug.info)
        # the same spot but the player between the raiser and hero still has cards: not hero's turn yet
        early = self.see(reader, self.spot(*self.RAISED, self.IN, pot=950))
        wait = suggest(early.table, LiveSettings(), HandMemory(), blocking=early.blocking)
        self.assertEqual(wait.kind, "wait")
        self.assertIn("Seat 6", wait.reason)
        forced = suggest(early.table, LiveSettings(), HandMemory(), force=True, blocking=early.blocking)
        self.assertEqual(forced.kind, "act")
        self.assertTrue(any("Seat 6" in w for w in forced.warnings))
        # nobody in yet and a player before hero has not acted: wait as well
        first = self.see(reader, self.spot([4975, 4975, 4875, 4775, 4975, 4975], [0, 0, 100, 200, 0, 0],
                                           [True, True, True, True, False, True], pot=450))
        self.assertEqual(suggest(first.table, LiveSettings(), HandMemory()).kind, "wait")
        folded = self.see(reader, self.spot([4975, 4975, 4875, 4775, 4975, 4975], [0, 0, 100, 200, 0, 0],
                                            [True, True, True, True, False, False], pot=450))
        sug = suggest(folded.table, LiveSettings(), HandMemory())
        self.assertIn("folded to you", sug.info)
        self.assertTrue(sug.action.startswith(("RAISE", "ALL-IN")), sug.action)

    def test_a_hand_is_followed_street_by_street(self):
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        reader, mem, tag = self.reader(), HandMemory(), LiveSettings()
        two = [True, False, False, False, True, False]
        frames = [
            self.spot([4975, 4975, 4875, 4775, 4975, 4975], [0, 0, 100, 200, 0, 0], self.IN, pot=450, turn=False),
            self.spot(*self.RAISED, self.IN, pot=950, turn=False),
            self.spot(*self.RAISED, [True, True, True, True, True, False], pot=950),
            self.spot([3675, 4975, 4875, 4775, 4475, 4975], [1300, 0, 100, 200, 500, 0], two, pot=2250, turn=False),
            self.spot([3675, 4975, 4875, 4775, 3675, 4975], [1300, 0, 100, 200, 1300, 0], two, pot=3050, turn=False),
            self.spot([3675, 4975, 4875, 4775, 3675, 4975], [0] * 6, two, pot=3050, board=self.BOARD),
            self.spot([2675, 4975, 4875, 4775, 3675, 4975], [1000, 0, 0, 0, 0, 0], two, pot=4050, turn=False,
                      board=self.BOARD),
            self.spot([2675, 4975, 4875, 4775, 2675, 4975], [1000, 0, 0, 0, 1000, 0], two, pot=5050, turn=False,
                      board=self.BOARD),
            self.spot([2675, 4975, 4875, 4775, 675, 4975], [0, 0, 0, 0, 2000, 0], two, pot=7050,
                      board=self.BOARD + ["9h"]),
        ]
        shown = []
        for spec in frames:
            res = self.see(reader, spec)
            self.assertEqual(res.blocking, [])
            sug = suggest(res.table, tag, mem, blocking=res.blocking)
            self.assertEqual((res.table.small_blind, res.table.big_blind), (100, 200))   # also after the raises
            if sug.kind == "act":
                shown.append(sug)
        pre, flop, turn = shown
        self.assertIn("raises to 2.5bb", pre.info)
        self.assertIn("checked to you", flop.info)
        self.assertIn("CO", flop.info)
        self.assertIn("18bb behind", flop.info)
        self.assertTrue(flop.action.startswith("BET"), flop.action)             # top pair, top kicker
        self.assertIn("to call 10.0bb", turn.info)
        self.assertTrue(turn.action.split()[0] in ("CALL", "RAISE", "FOLD"), turn.action)
        self.assertFalse(any("preflop action not seen" in w for s in (flop, turn) for w in s.warnings))
        # what it remembers: who opened, that hero re-raised, the flop call and the turn bet
        self.assertEqual(mem.roles, {"Seat 5": "open", "You": "3bet"})
        self.assertTrue(mem.hero_raised)
        self.assertEqual(mem.raises, 2)
        line = mem.lines["Seat 5"]
        self.assertEqual([(st, act) for st, act, _ in line], [("flop", "call"), ("turn", "bet")])
        self.assertAlmostEqual(line[1][2], 2000 / 5050, places=2)

    def test_what_it_cannot_read_stops_the_advice(self):
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        from poker_coach.live.local import LocalReader
        from poker_coach.live.vision import Book, CardBook, GlyphBook
        # a book that has never seen a 5: the raise to 500 cannot be read, so no advice (not "folded to you")
        chars = {c: v for c, v in self.book.glyphs.chars.items() if c != "5"}
        reader = LocalReader(self.layout, Book(GlyphBook(chars), self.book.cards), self.boxes["buttons"],
                             self.baseline)
        res = self.see(reader, self.spot([4974, 4974, 4874, 4774, 4474, 4974], [0, 0, 100, 200, 500, 0],
                                         [True, True, True, True, True, False], pot=944))
        self.assertTrue(any("seat 5 bet" in b for b in res.blocking), res.blocking)
        sug = suggest(res.table, LiveSettings(), HandMemory(), blocking=res.blocking)
        self.assertEqual(sug.kind, "error")
        self.assertIn("seat 5 bet", sug.reason)
        self.assertEqual(sug.action, "")
        # a board card it does not know: no advice, and never mistaken for "before the flop"
        ranks = {r: v for r, v in self.book.cards.ranks.items() if r != "7"}
        reader = LocalReader(self.layout, Book(self.book.glyphs, CardBook(ranks, self.book.cards.suits)),
                             self.boxes["buttons"], self.baseline)
        res = self.see(reader, self.spot([3675, 4975, 4875, 4775, 3675, 4975], [0] * 6,
                                         [True, False, False, False, True, False], pot=3050, board=self.BOARD))
        self.assertTrue(any("board card 2" in b for b in res.blocking), res.blocking)
        self.assertEqual(suggest(res.table, LiveSettings(), HandMemory(), blocking=res.blocking).kind, "error")

    def test_blinds_are_not_fooled_by_raises(self):
        reader = self.reader()
        hand1 = dict(hero=["Ah", "Kd"])
        folded = [False, False, True, True, False, False]
        self.see(reader, self.spot([4975] * 6, [0, 0, 100, 200, 0, 0], self.IN, pot=450, **hand1))
        self.assertEqual((reader.sb, reader.bb), (100, 200))
        # blind against blind: a raise to 600 and a re-raise to 1,800 look like blinds of 600/1,800
        self.see(reader, self.spot([4975, 4975, 4375, 3175, 4975, 4975], [0, 0, 600, 1800, 0, 0], folded, pot=2550,
                                   **hand1))
        self.assertEqual((reader.sb, reader.bb), (100, 200))
        # the next hand opens with that war already on: still not taken (blinds do not triple)
        self.see(reader, self.spot([4975, 4975, 4375, 3175, 4975, 4975], [0, 0, 600, 1800, 0, 0], folded, pot=2550,
                                   hero=["Qs", "Qc"]))
        self.assertEqual((reader.sb, reader.bb), (100, 200))
        # a new level
        self.see(reader, self.spot([4960] * 6, [0, 0, 150, 300, 0, 0], self.IN, pot=690, hero=["9c", "9d"]))
        self.assertEqual((reader.sb, reader.bb, reader.ante), (150, 300, 40))
        # a fresh reader that first sees the small blind already called: the big blind's chips are the blind
        fresh = self.reader()
        self.see(fresh, self.spot([4975, 4975, 4775, 4775, 4975, 4975], [0, 0, 200, 200, 0, 0], folded, pot=550))
        self.assertEqual(fresh.bb, 200)

    def test_blurred_digits_are_asked_not_misread(self):
        from PIL import Image, ImageDraw, ImageFont
        from poker_coach.live.vision import GlyphBook, parse_amount
        try:
            ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        except OSError:
            self.skipTest("needs the DejaVu font")

        def draw(text, ox, oy, size=13, scale=4):       # drawn large and shrunk: sub-pixel offsets
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size * scale)
            img = Image.new("RGB", (140 * scale, 40 * scale), (15, 15, 18))
            ImageDraw.Draw(img).text((12 * scale + ox, 8 * scale + oy), text, font=font, fill=(240, 240, 240))
            return img.resize((140, 40), Image.LANCZOS)

        book, rng = GlyphBook(), random.Random(5)
        asked = wrong = 0
        for i in range(120):
            value = rng.choice([rng.randint(100, 999), rng.randint(1000, 99999), rng.randint(100000, 2500000)])
            text = f"{value:,}"
            img = draw(text, rng.randrange(4), rng.randrange(4))
            got = book.read(img)
            if "?" in got or not got:
                asked += 1
                self.assertTrue(book.learn(img, text), text)
            elif parse_amount(got) != value:
                wrong += 1
        self.assertEqual(wrong, 0)
        self.assertLess(asked, 25)                      # it settles after a handful of answers

    def test_an_icon_in_the_box_is_taught_piece_by_piece(self):
        from PIL import Image, ImageDraw
        from fake_table import SMALL
        from poker_coach.live.local import PIECES, TeachItem, learn, learn_pieces
        from poker_coach.live.vision import Book, glyphs, parse_amount

        def bet_box(text):                               # a chip drawn next to the amount
            img = Image.new("RGB", (120, 26), (30, 110, 60))
            d = ImageDraw.Draw(img)
            d.ellipse((6, 5, 22, 21), fill=(250, 250, 250))
            d.text((34, 4), text, font=SMALL, fill=(255, 214, 10))
            return img
        book, img = Book(), bet_box("1,250")
        item = TeachItem("text", "seat 2 bet", img, pieces=glyphs(img))
        self.assertEqual(len(item.pieces), 6)
        self.assertEqual(learn(book, item, "1,250"), PIECES)
        self.assertEqual(learn_pieces(book, item, ["", "1", ",", "2", "5", "0"]), "")
        self.assertEqual(book.glyphs.read(img), "1,250")
        self.assertEqual(parse_amount(book.glyphs.read(bet_box("5,210"))), 5210)     # the chip reads as nothing

    def test_setup_checks(self):
        from poker_coach.live.capture import Rect
        from poker_coach.live.wizard import apply_boxes, layout_boxes, step_label, table_steps
        self.assertTrue(self.layout.clockwise())
        self.assertEqual(self.layout.advice(), [])
        swapped = copy.deepcopy(self.layout)
        swapped.seats[1], swapped.seats[4] = swapped.seats[4], swapped.seats[1]
        self.assertFalse(swapped.clockwise())
        self.assertTrue(any("clockwise" in a for a in swapped.advice()))
        short = copy.deepcopy(self.layout)
        short.board, short.pot = short.board[:3], None
        self.assertEqual(len(short.advice()), 2)
        # marking one box again changes that box only
        lay = copy.deepcopy(self.layout)
        apply_boxes(lay, {"s3_bet": Rect(1, 2, 30, 20), "board4": Rect(5, 6, 30, 50)}, {}, 6)
        self.assertEqual(lay.seats[2].bet, [1, 2, 30, 20])
        self.assertEqual(lay.board[3], [5, 6, 30, 50])
        self.assertEqual(lay.seats[2].stack, self.layout.seats[2].stack)
        self.assertEqual(lay.marker_template, self.layout.marker_template)
        keys = [s.key for s in table_steps(6)]
        self.assertEqual(set(layout_boxes(self.layout)) - set(keys), set())
        self.assertEqual(step_label("s3_bet"), "seat 3 bet")
        self.assertEqual(step_label("board4"), "board card 4")

    def test_loop_advises_once_per_spot(self):
        import queue
        import time as _t
        from fake_table import render
        from poker_coach.live import app
        two = [True, False, False, False, True, False]
        waiting = render(self.spot(*self.RAISED, self.IN, pot=950, turn=False))[0]
        mine = render(self.spot(*self.RAISED, [True, True, True, True, True, False], pot=950))[0]
        flop = render(self.spot([3675, 4975, 4875, 4775, 3675, 4975], [0] * 6, two, pot=3050,
                                board=self.BOARD))[0]
        frames = [waiting] * 4 + [mine] * 12 + [waiting] * 4 + [flop] * 400

        class Grab:
            k = 0

            def grab(self):
                Grab.k += 1
                return frames[min(Grab.k - 1, len(frames) - 1)]

        cfg = app.LiveConfig(region=[0, 0, 960, 640], save_images=False)
        out = queue.Queue()
        with tempfile.TemporaryDirectory() as tmp:
            old = app.LOG_ROOT
            app.LOG_ROOT = tmp
            old_gap, app.OBSERVE_EVERY = app.OBSERVE_EVERY, 0.0
            try:
                w = app.Worker(cfg, out, reader=self.reader(), grabber=Grab(), poll=0.002)
                w.start()
                deadline = _t.time() + 20
                while Grab.k < 60 and _t.time() < deadline:
                    _t.sleep(0.02)
                w.stopped.set()
                w.join(3)
            finally:
                app.LOG_ROOT, app.OBSERVE_EVERY = old, old_gap
        got = []
        while not out.empty():
            u = out.get()
            got.append(u.suggestion.action.split()[0] if u.suggestion else u.status)
        acts = [g for g in got if g.isupper()]
        self.assertEqual(len(acts), 2, got)                     # one for the raise, one for the flop
        self.assertIn("waiting for your turn", got)

    def test_random_spots_never_crash_or_give_an_illegal_move(self):
        from fake_table import render
        from poker_coach.live.decide import HandMemory, LiveSettings, suggest
        rng = random.Random(21)
        deck = [r + s for r in "23456789TJQKA" for s in "shdc"]
        seen = set()
        for i in range(40):
            rng.shuffle(deck)
            board = deck[2:2 + rng.choice([0, 3, 4, 5])]
            bets = [0, 0, 100, 200, 0, 0] if not board else [0] * 6
            cards = [True] + [rng.random() < 0.6 for _ in range(5)]
            raiser = rng.choice([4, 5, 2, 3])
            if rng.random() < 0.6:
                bets[raiser] = rng.choice([400, 500, 800, 2400])
                cards[raiser] = True
            if not any(cards[1:]):
                cards[4] = True
            if not board:                                # before the flop everybody in front of hero has acted
                for k in (4, 5):
                    cards[k] = cards[k] and bets[k] > 0
            stacks = [rng.randint(5, 80) * 200 for _ in range(6)]
            spec = self.spot(stacks, bets, cards, hero=deck[:2], board=board, pot=sum(bets) + rng.randint(1, 20) * 200)
            reader = self.reader()
            reader.sb, reader.bb = 100, 200
            res = reader.read(render(spec)[0])
            self.assertEqual(res.blocking, [], spec)
            for mode in ("tag", "binary"):
                sug = suggest(res.table, LiveSettings(mode=mode), HandMemory(), blocking=res.blocking)
                self.assertIn(sug.kind, ("act", "wait"), (sug.reason, spec))
                seen.add(sug.kind)
                if sug.kind != "act":
                    continue
                first = sug.action.split()[0]
                facing = max(b for k, b in enumerate(bets) if k and cards[k]) > 0 if board else False
                if board and facing:
                    self.assertIn(first, ("CALL", "FOLD", "RAISE"), (sug.action, sug.info))
                elif board:
                    self.assertIn(first, ("CHECK", "BET"), (sug.action, sug.info))
        self.assertIn("act", seen)
