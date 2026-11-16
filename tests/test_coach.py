"""Tests for the poker coach engine.  Run: python -m unittest discover -s tests"""

import io
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
                self.assertGreater(slow, cost)
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
        # 180 left, 150 paid: the line is one average stack
        self.assertAlmostEqual(L.sit_out_line(50000, 180, 150), 50000.0)
        self.assertEqual(L.zone(70000, 50000, 180, 150)[0], "safe")
        self.assertEqual(L.zone(40000, 50000, 180, 150)[0], "close")
        self.assertEqual(L.zone(15000, 50000, 180, 150)[0], "short")
        self.assertEqual(L.zone(1000, 50000, 450, 150)[0], "far")
        self.assertEqual(L.zone(1, 50000, 150, 150)[0], "safe")
        lines = [L.sit_out_line(50000, r, 150) for r in (151, 155, 165, 180, 225, 300, 450, 700)]
        self.assertTrue(all(a < b for a, b in zip(lines, lines[1:])), lines)
        self.assertTrue(all(L.cash_chance(a) <= L.cash_chance(b) for a, b in ((0.0, 0.1), (0.1, 0.3), (0.3, 1.0))))
        self.assertIn("SIT OUT", L.describe_zone(70000, 50000, 180, 150))
        self.assertIn("KEEP PLAYING", L.describe_zone(5000, 50000, 300, 150))
        self.assertEqual([L.seat_name(b, 8) for b in range(7, 0, -1)], ["UTG", "UTG+1", "LJ", "HJ", "CO", "BTN", "SB"])
        self.assertEqual([L.seat_name(b, 6) for b in range(5, -1, -1)], ["LJ", "HJ", "CO", "BTN", "SB", "BB"])
        self.assertEqual(L.seat_name(6, 7), "UTG")
        ordinary = L.scout(16, 500, 150, entrants=1000, speed="turbo", buyin=10, fee=0.8)
        close = L.scout(16, 190, 150, entrants=320, speed="turbo", buyin=10, fee=0.8)
        self.assertLess(ordinary.itm, 0.35)
        self.assertGreater(close.itm, 0.6)
        self.assertLess(ordinary.cover, close.cover)
        self.assertIn(ordinary.verdict, ("SKIP", "MARGINAL"))
        bounty = L.scout(16, 500, 150, entrants=1000, speed="turbo", buyin=10, fee=0.8, bounty_share=0.5)
        self.assertLess(bounty.min_cash, ordinary.min_cash)
        self.assertLess(bounty.roi, ordinary.roi)
        fixed = L.payouts_with_min_cash(1000, 150, 10000.0, 21.0)
        self.assertAlmostEqual(fixed[-1], 21.0)
        self.assertAlmostEqual(sum(fixed), 10000.0, places=4)

    def test_cli(self):
        for args, code in ((["latereg", "--stack-bb", "16", "--left", "190", "--paid", "150", "--entries", "1000"], 0),
                           (["latereg", "--stack", "8000", "--bb", "500", "--left", "26", "--paid", "8",
                             "--avg", "16320", "--buyin", "27.6", "--fee", "2.4", "--chart"], 0),
                           (["latereg-safe", "--stack", "34k", "--avg", "52000", "--left", "180", "--paid", "150"], 0),
                           (["latereg", "--stack-bb", "16", "--left", "190", "--paid", "150"], 2)):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                got = main(args)
            self.assertEqual(got, code, (args, err.getvalue()))

