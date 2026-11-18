"""Tests for the poker coach engine.  Run: python -m unittest discover -s tests"""

import copy
import io
import json
import os
import random
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
        from poker_coach.live.local import TeachItem, learn
        from poker_coach.live.reader import ReadError
        from poker_coach.live.vision import Book
        img = render(self.SETUP)[0]
        with self.assertRaises(ReadError):
            self.reader().read(img.resize((800, 533)))
        crop = img.crop((self.boxes["seats"][0]["stack"][0], self.boxes["seats"][0]["stack"][1],
                         self.boxes["seats"][0]["stack"][0] + 120, self.boxes["seats"][0]["stack"][1] + 26))
        book = Book()
        self.assertIn("separate characters", learn(book, TeachItem("text", "your stack", crop), "5000"))
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
