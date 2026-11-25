"""The quick guide: the engine's looser style, the table builder, the tables and the page's files.

The page itself (guide/guide.js) is checked in a browser, not here: for random spots its answer is compared
with the engine asked directly at the real table size.  What is checked here needs no browser.
"""
import dataclasses
import json
import os
import random
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_guide as B                                        # noqa: E402
import build_guide_page                                        # noqa: E402
from poker_coach import preflop as P                           # noqa: E402
from poker_coach import ranges as R                            # noqa: E402
from poker_coach.cards import HANDS, parse_hand, range_pct     # noqa: E402

GUIDE = os.path.join(ROOT, "guide")


def go(hand, stack, pos, facing="", players=9, opp=None):
    h, cards = parse_hand(hand)
    spot = P.quick_spot(h, cards, stack, players, pos, facing)
    if opp:
        spot.types = [opp] * players
    return P.advise(spot)


class LooserStyle(unittest.TestCase):
    """``ranges.set_style("win")``: what the guide's "Play to win" asks the engine for."""

    def tearDown(self):
        R.set_style("tag")

    def test_the_default_is_the_tight_style_and_the_switch_gives_it_back(self):
        self.assertEqual(R.style(), "tag")
        with R.use_style("win"):
            self.assertEqual(R.style(), "win")
            with R.use_style("tag"):
                self.assertEqual(R.style(), "tag")
            self.assertEqual(R.style(), "win")
        self.assertEqual(R.style(), "tag")
        with self.assertRaises(ValueError):
            R.set_style("loose")
        self.assertEqual(R.style(), "tag")

    def test_the_looser_rows_hold_the_tight_ones_at_every_depth(self):
        for nb in range(8, 0, -1):
            for eff in (100, 50, 30, 22, 14):
                tight = R.rfi_range(nb, eff)
                with R.use_style("win"):
                    loose = R.rfi_range(nb, eff)
                self.assertFalse([HANDS[h] for h in range(169) if tight[h] >= 0.5 > loose[h]], (nb, eff))
                if nb == 2 and eff <= 25:           # the button with 25bb or less: the tight row is a solver's width, and both styles open it
                    self.assertEqual(loose, tight, (nb, eff))
                else:
                    self.assertGreater(range_pct(loose), range_pct(tight), (nb, eff))

    def test_the_looser_rows_widen_seat_by_seat(self):
        with R.use_style("win"):
            widths = [range_pct(R.rfi_range(nb, 50)) for nb in range(8, 1, -1)]      # first seat ... button
        self.assertEqual(widths, sorted(widths))
        self.assertTrue(12 < widths[0] < 15, widths)                                 # nine players, first to act
        self.assertTrue(34 < widths[5] < 38, widths)                                 # cutoff
        self.assertTrue(47 < widths[6] < 53, widths)                                 # button

    def test_opponents_are_taken_to_open_the_same_rows(self):
        for nb in (8, 5, 3, 2):
            tight = range_pct(R.villain_open_range(nb, "unknown", 40))
            with R.use_style("win"):
                loose = range_pct(R.villain_open_range(nb, "unknown", 40))
                mine = range_pct(R.rfi_range(nb, 40))
            self.assertGreater(loose, tight, nb)
            self.assertAlmostEqual(loose, mine, delta=0.6, msg=nb)

    def test_first_in_a_hand_of_the_looser_row_is_raised(self):
        self.assertEqual(go("A7o", 40, "CO").action, "FOLD")
        with R.use_style("win"):
            adv = go("A7o", 40, "CO")
        self.assertTrue(adv.action.startswith("RAISE"), adv.action)
        self.assertNotIn("TAG", " ".join(adv.why))

    def test_with_13_to_16bb_it_raises_small_where_the_all_in_does_not_earn(self):
        """The tight style folds a hand that is no all-in at that depth; the looser one raises the hands of its row."""
        spot = P.quick_spot(0, None, 15.0, 9, "CO", "")
        tight = [P.advise(dataclasses.replace(spot, hand=h)).action for h in range(169)]
        with R.use_style("win"):
            loose = [P.advise(dataclasses.replace(spot, hand=h)).action for h in range(169)]
            row = R.rfi_range(3, 15)
        raised = [h for h in range(169) if tight[h] == "FOLD" and loose[h].startswith("RAISE")]
        self.assertGreater(len(raised), 8)
        self.assertTrue(all(row[h] >= 0.5 for h in raised))
        self.assertTrue(all(loose[h] == "RAISE to 2.0bb" for h in raised))
        # nothing the tight style plays is folded by the looser one, and every all-in stays an all-in
        self.assertFalse([HANDS[h] for h in range(169) if tight[h] != "FOLD" and loose[h] == "FOLD"])
        self.assertFalse([HANDS[h] for h in range(169) if tight[h] == "ALL-IN" and loose[h] != "ALL-IN"])
        # under 13bb there is no small raise in either style
        short = P.quick_spot(0, None, 11.0, 9, "CO", "")
        with R.use_style("win"):
            self.assertFalse([h for h in range(169) if P.advise(dataclasses.replace(short, hand=h)).action == "RAISE to 2.0bb"])

    def test_the_big_blind_calls_where_the_call_is_worth_more_than_the_all_in(self):
        """A suited connector moved all-in for 20bb to win 0.05bb, where a call of 1bb is worth far more."""
        with R.use_style("win"):
            for hand in ("76s", "T8s", "A2o", "K5s"):
                adv = go(hand, 20, "BB", "CO raise 2bb")
                self.assertEqual(adv.action, "CALL", hand)
                if "call_value_bb" in adv.data:
                    self.assertGreaterEqual(adv.data["call_value_bb"], adv.data["reshove_ev_bb"], hand)
            for hand in ("AJo", "99", "A9s", "55"):
                self.assertEqual(go(hand, 20, "BB", "CO raise 2bb").action, "ALL-IN", hand)
            # the small blind has no such call: it is all-in or fold there
            self.assertIn(go("A9o", 20, "SB", "CO raise 2bb").action, ("ALL-IN", "FOLD"))
            # a call well over its price is not "close" in this style
            self.assertEqual(go("J9s", 20, "BB", "BTN raise 2bb").confidence, "standard")

    def test_the_looser_style_never_moves_all_in_on_a_thinner_edge(self):
        """Its width comes from the rows and from the calls, not from a lower bar for the all-in."""
        with R.use_style("win"):
            for hand, stack, pos, facing in (("KTs", 20, "BTN", "UTG raise 2bb"), ("QJs", 20, "BTN", "UTG raise 2bb")):
                adv = go(hand, stack, pos, facing)
                if adv.action == "ALL-IN":
                    self.assertGreater(adv.data["reshove_ev_bb"], 0.15, hand)
        with open(os.path.join(ROOT, "poker_coach", "preflop.py")) as fh:
            source = fh.read()
        self.assertEqual(len(re.findall(r"_bar\(", source)), 4, "one definition and the three uses after a re-raise")


class ShortStackRows(unittest.TestCase):
    """With 25bb or less the looser style opens what a solver opens from the cutoff and the button."""

    def tearDown(self):
        R.set_style("tag")

    def test_the_button_opens_41_percent_with_25bb_or_less_and_half_its_hands_deeper(self):
        with R.use_style("win"):
            self.assertAlmostEqual(range_pct(R.rfi_range(2, 20)), 40.6, delta=0.2)      # a solver: 41.5% with 20bb
            self.assertAlmostEqual(range_pct(R.rfi_range(2, 25)), 40.6, delta=0.2)
            self.assertAlmostEqual(range_pct(R.rfi_range(2, 26)), 49.6, delta=0.2)
            self.assertAlmostEqual(range_pct(R.rfi_range(3, 20)), 31.8, delta=0.2)      # the cutoff: a solver's 31.2%
            self.assertEqual(R.rfi_range(2, 20), list(R._ladder(2)))                    # the tight style's button row
            # one notch wider than the short row is the full row; one tighter, the cutoff's
            self.assertAlmostEqual(range_pct(R.rfi_range(2, 20, -1)), 49.6, delta=0.2)
            self.assertAlmostEqual(range_pct(R.rfi_range(2, 20, 1)), 35.7, delta=0.2)
            self.assertEqual(R.rfi_range(1, 20), R.rfi_range(1, 100))                   # the small blind keeps its row

    def test_a_raise_from_the_cutoff_or_the_button_is_read_as_that_row(self):
        with R.use_style("win"):
            for nb in (2, 3):
                self.assertEqual(R.villain_open_range(nb, "unknown", 20), R.rfi_range(nb, 20))
                self.assertGreater(range_pct(R.villain_open_range(nb, "unknown", 30)), range_pct(R.villain_open_range(nb, "unknown", 20)) + 3)
                tight, usual, loose = (range_pct(R.villain_open_range(nb, t, 20)) for t in ("tight", "unknown", "loose"))
                self.assertLess(tight, usual)
                self.assertLess(usual, loose)
            for nb in (4, 5, 6, 7, 8, 1):          # the seats before them keep the full row: it is no wider than a solver's
                self.assertEqual(R.villain_open_range(nb, "unknown", 20), R.villain_open_range(nb, "unknown", 100), nb)

    def test_the_other_styles_read_a_raise_as_they_did(self):
        for style in ("tag", "tight"):
            with R.use_style(style):
                for nb in range(1, 9):
                    self.assertEqual(R.villain_open_range(nb, "unknown", 20), R.villain_open_range(nb, "unknown", 100), (style, nb))
                self.assertEqual(R.rfi_range(2, 20), R.rfi_range(2, 100))

    def test_with_13_to_20bb_the_button_plays_about_what_a_solver_plays(self):
        """Raise and all-in together: 41.5% for a solver with 20bb; the full row made it 50%."""
        with R.use_style("win"):
            for stack in (14, 17, 20):
                letters = B.table(2, stack, "", "unknown")["a"]
                played = sum(c for c, ch in zip(B.COMBO_COUNT, letters) if ch not in "fF") / 13.26
                self.assertTrue(38 < played < 46, (stack, played))


class Builder(unittest.TestCase):
    def tearDown(self):
        R.set_style("tag")

    def test_packing_a_table_and_unpacking_it(self):
        rng = random.Random(4)
        for _ in range(200):
            letters = "".join(rng.choice("ffffffrRacxX") * rng.randint(1, 9) for _ in range(40))[:169].ljust(169, "f")
            self.assertEqual(B.unpack(B.pack(letters)), letters)
        self.assertEqual(B.pack("f" * 169), "f169")
        self.assertEqual(B.pack("rrrfff"), "rrrfff")

    def test_every_answer_the_engine_gives_has_a_letter(self):
        class Fake:
            def __init__(self, action, confidence="standard"):
                self.action, self.confidence = action, confidence
        cases = {"FOLD": "FOLD", "CHECK": "CHECK", "CHECK / take the walk": "CHECK", "CALL": "CALL",
                 "CALL (limp behind)": "LIMP", "RAISE to 2.2bb": "RAISE", "RAISE to 4bb": "RAISE",
                 "RAISE to 2.0bb and call any all-in": "RAISE_CALL", "3-BET to 7.5bb": "RERAISE",
                 "4-BET to 22bb": "RERAISE", "3-BET to 7.5bb (semi-bluff, fold to a 4-bet)": "RERAISE_BLUFF",
                 "ALL-IN": "ALLIN", "3-BET to 30bb (puts the opener all-in)": "ALLIN",
                 "RE-RAISE to 12bb (isolate)": "ISOLATE", "RE-RAISE ALL-IN (isolate)": "ISOLATE_ALLIN"}
        for text, name in cases.items():
            self.assertEqual(B.ACTIONS[B.CODES.index(B.code_of(Fake(text)))], name, text)
            self.assertEqual(B.ACTIONS[B.CLOSE.index(B.code_of(Fake(text, "close")))], name, text)
        with self.assertRaises(ValueError):
            B.code_of(Fake("WAIT"))
        self.assertEqual(len(set(B.CODES + B.CLOSE)), 22)

    def test_a_table_is_the_engines_answer_hand_by_hand(self):
        """The builder keeps the solver's answers for the 169 hands of a spot: that must not change one."""
        for style, question in (("win", dict(hero_nb=3, stack=20, facing="")),
                                ("win", dict(hero_nb=0, stack=18, facing="BTN raise 2.0bb")),
                                ("tag", dict(hero_nb=2, stack=14, facing="hero raise 2.0bb, BB allin"))):
            R.set_style(style)
            made = B.table(opp="unknown", **question)
            spot = P.quick_spot(0, None, float(question["stack"]), 9, B.seat(question["hero_nb"]), question["facing"])
            plain = "".join(B.pairs_in_order([B.code_of(P.advise(dataclasses.replace(spot, hand=h))) for h in range(169)]))
            self.assertEqual(made["a"], plain, (style, question))

    def test_pairs_keep_their_order(self):
        """Tens do not call where jacks fold: the higher pair takes the lower pair's play."""
        fold = ["f"] * 169
        tens, jacks, queens, nines = (B.HANDS.index(h) for h in ("TT", "JJ", "QQ", "99"))
        letters = list(fold)
        letters[tens] = "C"                     # a close call
        letters[B.HANDS.index("AA")] = letters[B.HANDS.index("KK")] = "c"
        out = B.pairs_in_order(letters)
        self.assertEqual((out[jacks], out[queens], out[tens], out[nines]), ("C", "C", "C", "f"))
        self.assertEqual(sum(1 for a, b in zip(out, letters) if a != b), 2)
        ordered = list(fold)
        for hand in ("AA", "KK", "QQ"):
            ordered[B.HANDS.index(hand)] = "a"
        self.assertEqual(B.pairs_in_order(ordered), ordered)
        self.assertEqual(B.pairs_in_order(B.pairs_in_order(letters)), out)

    def test_the_builder_leaves_the_engine_as_it_found_it(self):
        """It keeps the solver's answers while it asks about one spot, and only then."""
        names = B._SOLVERS + ("solve_shove",)
        before = [getattr(P, name) for name in names]
        with B.one_solve_per_spot():
            self.assertTrue(all(getattr(P, name) is not plain for name, plain in zip(names, before)))
        self.assertEqual([getattr(P, name) for name in names], before)
        B.table(hero_nb=2, stack=12, facing="", opp="unknown")
        self.assertEqual([getattr(P, name) for name in names], before)
        self.assertEqual(B._memo, {})

    def test_every_family_asks_questions_the_engine_can_read(self):
        counts = {}
        for name, (what, make) in B.FAMILIES.items():
            keys = set()
            for key, question in make():
                self.assertNotIn(key, keys, name)
                keys.add(key)
                self.assertIn(key[-1], B.STACKS, name)
                spot = P.quick_spot(0, None, float(question["stack"]), question.get("players", 9),
                                    question.get("hero_seat") or B.seat(question["hero_nb"]), question["facing"])
                self.assertEqual(len(spot.acts), question["facing"].count(",") + 1 if question["facing"] else 0, (name, key))
            counts[name] = len(keys)
            self.assertIn("[", what, name)
        self.assertEqual(counts["open"], 8 * len(B.STACKS))
        self.assertEqual(counts["allin"], 36 * len(B.SHORT))
        self.assertGreater(sum(counts.values()), 5000)

    def test_the_spots_priced_with_dealt_out_boards_are_few(self):
        """A raise and a call with 5bb or less are two all-ins (14 seconds a spot): the page reads that table."""
        for key, _ in B.fam_vsraise():
            self.assertFalse(key[2] and key[4] <= 5, key)


class RaiseSizes(unittest.TestCase):
    """A raise before the user comes in five sizes, a re-raise of their raise in four."""

    def tearDown(self):
        R.set_style("tag")

    def test_the_sizes_are_in_the_keys_and_never_the_whole_stack(self):
        sizes = set()
        for key, question in B.fam_vsraise():
            o, h, callers, zi, stack = key
            self.assertLess(B.RAISE_SIZES[zi], stack, key)
            self.assertIn(f"raise {B.RAISE_SIZES[zi]}bb", question["facing"], key)
            sizes.add(zi)
        self.assertEqual(sizes, set(range(len(B.RAISE_SIZES))))
        for key, question in B.fam_re3():
            h, who, zi, stack = key
            mine = B.open_size(stack, h)
            self.assertIn(f"hero raise {mine}bb", question["facing"], key)
            self.assertIn(f"raise {round(B.RERAISE_TIMES[zi] * mine, 1)}bb", question["facing"], key)
        self.assertEqual(B.parts_of("vsraise"), list(range(len(B.RAISE_SIZES))))
        self.assertEqual(sum(1 for _ in B.spots_of("vsraise", 2)), sum(1 for key, _ in B.fam_vsraise() if key[3] == 2))

    def test_a_raise_that_commits_the_raiser_has_a_table_only_without_callers(self):
        """Two fifths of the stack: the engine prices such a raise as an all-in, and behind callers with dealt-out
        boards (14 seconds a spot).  The builder leaves those out, and the page does not offer the size."""
        with R.use_style("win"):
            self.assertIn("committed", go("AQs", 10, "BB", "CO raise 4bb").situation)
            self.assertNotIn("committed", go("AQs", 10, "BB", "CO raise 3.9bb").situation)
        self.assertEqual(B.COMMITS, 0.4)
        for size, stack, callers, own in ((4.0, 10, 0, True), (4.0, 10, 1, False), (4.0, 11, 1, True), (2.0, 5, 1, False),
                                          (2.0, 6, 2, True), (2.0, 2, 0, False), (2.0, 3, 0, True), (2.5, 6, 1, False), (3.0, 8, 1, True)):
            self.assertEqual(B.own_table(size, stack, callers), own, (size, stack, callers))
        for key, _ in B.fam_vsraise():
            self.assertTrue(B.own_table(B.RAISE_SIZES[key[3]], key[4], key[2]), key)
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        cases = [(size, stack, callers) for size in B.RAISE_SIZES for stack in B.STACKS for callers in (0, 1, 2)]
        script = ("global.window = {}; global.document = {readyState: 'loading', addEventListener() {}};"
                  f"require({json.dumps(os.path.join(GUIDE, 'guide.js'))});"
                  f"console.log(JSON.stringify({json.dumps(cases)}.map(([z, s, c]) => window.MenloGuide.ownTable(z, s, c, {B.COMMITS}))));")
        got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(got, [B.own_table(*case) for case in cases])

    def test_the_usual_size_is_the_engines_own(self):
        usual = B.usual_sizes()
        for stack in B.STACKS:
            other, small_blind, two = usual["raise"][str(stack)]
            self.assertEqual(B.RAISE_SIZES[other], min(B.RAISE_SIZES, key=lambda z: abs(z - R.open_size_bb(stack, 3, True))), stack)
            self.assertEqual(B.RAISE_SIZES[small_blind], min(B.RAISE_SIZES, key=lambda z: abs(z - R.open_size_bb(stack, 1, True))), stack)
            self.assertIn(B.RAISE_SIZES[two], (2.0, 2.2))
            self.assertEqual(usual["open"][str(stack)][:2], [R.open_size_bb(stack, 3, True), R.open_size_bb(stack, 1, True)])
        self.assertEqual({k: B.RERAISE_TIMES[v] for k, v in usual["reraise"].items()}, {"2": 3.0, "1": 4.0, "0": 4.0})
        # the re-raises the page names are the ones the engine was asked about, to the tenth of a big blind
        asked = {(h, zi, stack): question["facing"].split("raise ")[2] for (h, who, zi, stack), question in B.fam_re3()}
        for (h, zi, stack), text in asked.items():
            self.assertEqual(f"{usual['reraise_to'][str(stack)][1 if h == 1 else 0][zi]}bb", text, (h, zi, stack))
        for (zi, stack), question in B.FAMILIES["hu_re3"][1]():
            self.assertEqual(f"{usual['reraise_to'][str(stack)][2][zi]}bb", question["facing"].split("raise ")[2], (zi, stack))

    def test_the_price_given_to_the_page_is_the_engines(self):
        """The big blind's price: with the small blind folding, raising or calling, and with two players."""
        R.set_style("win")
        cases = [("vsraise", (3, 0, 0, 3, 25), "CO raise 3.0bb", 9), ("vsraise", (2, 0, 0, 0, 20), "BTN raise 2.0bb", 9),
                 ("vsraise", (1, 0, 0, 3, 30), "SB raise 3.0bb", 9), ("vsraise", (2, 0, 1, 1, 30), "BTN raise 2.2bb, SB call", 9),
                 ("vsraise", (4, 0, 2, 2, 40), "HJ raise 2.5bb, CO call, BTN call", 9), ("hu_vsraise", (2, 30), "SB raise 2.5bb", 2)]
        for family, key, facing, players in cases:
            adv = go("AA", key[-1], "BB", facing, players=players)
            price = adv.data["bb_call_need"] * adv.data["bb_realised"] - adv.data["bb_over"]
            given = B.bb_price(family, key)
            self.assertAlmostEqual(given["p"], price, places=3, msg=(family, key))
            self.assertEqual(given.get("ip", 0), 1 if facing.startswith("SB raise") and players > 2 else 0, (family, key))


class BigBlindCall(unittest.TestCase):
    """The guide's test for the big blind's call of a raise: what the hand keeps of its equity against the price."""

    def tearDown(self):
        R.set_style("tag")

    def folds(self, style, opener, stack, size, players=8, more=""):
        R.set_style(style)
        made = B.table(hero_nb=0, stack=stack, facing=f"{opener} raise {size}bb{more}", opp="unknown", players=players, hero_seat="BB")
        return range_pct([1.0 if ch in "fF" else 0.0 for ch in made["a"]])

    def test_the_share_a_hand_keeps_is_in_a_sensible_order(self):
        share = lambda hand, stack=40, last=False: P.bb_realised(HANDS.index(hand), stack, last)      # noqa: E731
        for better, worse in (("T9s", "T9o"), ("T9o", "T7o"), ("T9o", "32s"), ("KQo", "K2o"), ("A5s", "A6s"), ("JTs", "J2s"),
                              ("99", "22"), ("98s", "43s"), ("AJo", "A7o"), ("76s", "72s"), ("Q9o", "Q2o")):
            self.assertGreater(share(better), share(worse), (better, worse))
        for hand in HANDS:
            self.assertTrue(0.45 < share(hand) <= 1.05, hand)
            self.assertGreater(share(hand, last=True), share(hand) - 1e-9, hand)                 # acting last keeps more
        self.assertLess(share("K7o", 100), share("K7o", 25))                                     # deeper, an offsuit hand keeps less
        self.assertEqual(share("K7s", 100), share("K7s", 25))

    def test_a_connected_hand_calls_where_a_small_suited_one_folds(self):
        """The default test gives every suited hand the same points: it called 32s against a raise to 3bb and folded T9o."""
        with R.use_style("win"):
            self.assertEqual(go("32s", 25, "BB", "CO raise 3bb").action, "FOLD")
            self.assertEqual(go("T9o", 25, "BB", "CO raise 3bb").action, "CALL")
            adv = go("T9o", 25, "BB", "CO raise 3bb")
            self.assertIn("turns into chips", " ".join(adv.numbers))
            self.assertAlmostEqual(adv.data["bb_realised"], P.bb_realised(HANDS.index("T9o"), 24, False), delta=0.01)

    def test_a_smaller_raise_is_called_with_more_hands_and_a_bigger_one_with_fewer(self):
        for style in ("win", "tight"):
            for opener, stack in (("UTG", 40), ("CO", 30), ("BTN", 25)):
                by_size = [self.folds(style, opener, stack, size) for size in (2.0, 2.2, 2.5, 3.0, 4.0)]
                self.assertEqual(by_size, sorted(by_size), (style, opener, stack))
                self.assertGreater(by_size[-1] - by_size[0], 25, (style, opener, stack))

    def test_it_folds_about_as_often_as_a_solver(self):
        """GTO Wizard's fold rates for the big blind, as printed by PokerNews (May 2026): a raise from the first
        seat with 25, 50 and 100bb, and from the cutoff with 100bb."""
        solver = [("UTG", 25, 2.0, 27.4), ("UTG", 25, 3.0, 71.4), ("UTG", 50, 2.0, 32.2), ("UTG", 50, 3.0, 72.7),
                  ("UTG", 100, 2.1, 37.3), ("UTG", 100, 3.0, 72.6), ("CO", 100, 2.2, 22.7), ("CO", 100, 3.0, 46.9)]
        for opener, stack, size, want in solver:
            win, tight = self.folds("win", opener, stack, size), self.folds("tight", opener, stack, size)
            self.assertLess(abs(win - want), 6 if opener == "UTG" else 12, (opener, stack, size, win, want))
            self.assertGreater(win, want - 4, (opener, stack, size))            # never looser than the solver by more than a little
            self.assertGreater(tight, win + 5, (opener, stack, size))           # the tight style asks more

    def test_a_call_is_a_call_exactly_when_the_equity_is_there(self):
        with R.use_style("win"):
            spot = P.quick_spot(0, None, 40.0, 9, "BB", "CO raise 2.5bb")
            for h in range(169):
                adv = P.advise(dataclasses.replace(spot, hand=h))
                if adv.action in ("CALL", "FOLD"):
                    self.assertEqual(adv.action == "CALL", adv.data["bb_call_edge"] >= 0, HANDS[h])
                    self.assertEqual(adv.confidence == "close", abs(adv.data["bb_call_edge"]) < P._BB_CLOSE or
                                     (adv.action == "CALL" and adv.data["bb_call_edge"] < P._BB_CLOSE), HANDS[h])

    def test_the_guide_calls_by_the_price_at_every_depth(self):
        """The default style calls a raise only when it costs 12% of the stack or less: with 9bb it folds half
        its hands to the smallest raise.  The guide's styles have no such step."""
        for style in ("win", "tight"):
            by_stack = [self.folds(style, "BTN", stack, 2.0) for stack in (6, 8, 10, 15, 25)]
            self.assertLess(max(by_stack) - min(by_stack), 4, (style, by_stack))
            for size, stacks in ((2.5, (7, 10, 14, 20)), (3.0, (8, 12, 17, 25)), (4.0, (12, 18, 25))):
                by_stack = [self.folds(style, "BTN", stack, size) for stack in stacks]
                self.assertLess(max(by_stack) - min(by_stack), 8, (style, size, by_stack))
        self.assertGreater(self.folds("tag", "BTN", 9, 2.0), self.folds("tag", "BTN", 10, 2.0) + 30)     # the default: as it was
        with R.use_style("win"):
            adv = go("T7s", 8, "BB", "BTN raise 2bb")
            self.assertEqual(adv.action, "CALL")
            self.assertIn("any pair or any draw", " ".join(adv.why + adv.warnings))
            self.assertEqual(go("K9s", 8, "BB", "BTN raise 2bb").action, "ALL-IN")       # an all-in that earns more stays one
            self.assertEqual(go("72o", 8, "BB", "BTN raise 2bb").action, "FOLD")
            self.assertEqual(go("Q4o", 8, "BB", "BTN raise 3bb").action, "FOLD")         # a bigger raise is another price
            self.assertNotIn("any pair", " ".join(go("T7s", 20, "BB", "BTN raise 2bb").why + go("T7s", 20, "BB", "BTN raise 2bb").warnings))
        self.assertNotEqual(go("96s", 8, "BB", "BTN raise 2bb").action, "CALL")

    def test_acting_last_it_folds_little_to_a_raise_from_the_small_blind(self):
        """GTO Wizard, as printed by PokerNews (September 2026): to a 2bb raise from the small blind the big
        blind folds 0.7% of hands with 100bb, "little" with 50bb and next to none with 25bb; to 3.5bb with
        100bb it calls 56.8% and re-raises more."""
        for stack in (25, 50, 100):
            self.assertLess(self.folds("win", "SB", stack, 2.0, players=9), 8, stack)
            self.assertLess(self.folds("tight", "SB", stack, 2.0, players=9), 16, stack)
        three, four = self.folds("win", "SB", 100, 3.0, players=9), self.folds("win", "SB", 100, 4.0, players=9)
        self.assertTrue(22 < three < 40 and three + 8 < four < 55, (three, four))
        # out of position the same price folds far more: against the button, and against the small blind of two players
        self.assertGreater(self.folds("win", "BTN", 100, 3.0, players=9), three + 12)
        self.assertGreater(self.folds("win", "SB", 20, 2.0, players=2), self.folds("win", "SB", 20, 2.0, players=9) + 12)
        share = lambda hand, last: P.bb_realised(HANDS.index(hand), 40, last)      # noqa: E731
        self.assertAlmostEqual(share("J7o", True) - share("J7o", False), P._BB_IN_POSITION)
        self.assertEqual(share("KQs", True), P._BB_SHARE_MOST_LAST)
        self.assertEqual(share("KQs", False), P._BB_SHARE_MOST)
        # the default style is as it was: two thirds of its points
        self.assertAlmostEqual(P.bb_call_points("off", in_position=True), P.bb_call_points("off") * 2 / 3)

    def test_with_callers_in_the_pot_their_hands_count(self):
        """The price of the big blind's call counts the callers' chips, so the equity counts their hands.  (It was
        taken against the raiser alone: with two callers in, 95% of hands called a cutoff raise.)"""
        from poker_coach.equity import eq_vs_range
        alone, one, two = (self.folds("win", "CO", 40, 2.0, players=9, more=more) for more in ("", ", BTN call", ", BTN call, SB call"))
        self.assertTrue(alone + 10 < one < alone + 25 and one < two < one + 18, (alone, one, two))
        with R.use_style("win"):
            line = "CO raise 2.2bb, BTN call"
            for hand, action in (("T9s", "CALL"), ("K7s", "CALL"), ("A5o", "CALL"), ("98o", "CALL"), ("Q5o", "FOLD"), ("72o", "FOLD"), ("J4o", "FOLD")):
                self.assertEqual(go(hand, 40, "BB", line).action, action, hand)
            adv = go("T9o", 40, "BB", line)
            against_raiser = float(re.search(r"your equity vs it (\d+)%", " ".join(adv.numbers)).group(1)) / 100
            self.assertLess(adv.data["bb_equity"], against_raiser - 0.08)
            self.assertAlmostEqual(adv.data["bb_equity"], P.beats_all([eq_vs_range(HANDS.index("T9o"), r)[0] for r in
                                   (R.villain_open_range(3, "unknown", 39.0), P.flat_range(3, 2))]), places=6)
            self.assertIn("against the raiser and the caller together", " ".join(adv.numbers))
            # the margin is a part of a fair share: a third less with one caller, half with two
            self.assertAlmostEqual(adv.data["bb_over"], P._BB_MARGIN["win"] * 2 / 3)
            self.assertAlmostEqual(go("T9o", 40, "BB", line + ", SB call").data["bb_over"], P._BB_MARGIN["win"] / 2)
            self.assertAlmostEqual(go("T9o", 40, "BB", "CO raise 2.2bb").data["bb_over"], P._BB_MARGIN["win"])
        # the default style is as it was: the raiser alone, and three points more for offsuit hands
        R.set_style("tag")
        self.assertNotIn("bb_equity", go("T9o", 40, "BB", "CO raise 2.2bb, BTN call").data)
        self.assertAlmostEqual(P.bb_call_points("off", callers=1) - P.bb_call_points("off"), 0.0)       # capped at 15 points
        self.assertAlmostEqual(P.bb_call_points("broadway_off", callers=1) - P.bb_call_points("broadway_off"), 0.03)
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        cases = [[0.5, 0.5], [0.4], [0.85, 0.85], [0.37, 0.36, 0.41], [0.3, 0.0], [0.62]]
        script = ("global.window = {}; global.document = {readyState: 'loading', addEventListener() {}};"
                  f"require({json.dumps(os.path.join(GUIDE, 'guide.js'))});"
                  f"console.log(JSON.stringify({json.dumps(cases)}.map((e) => window.MenloGuide.beatsAll(e))));")
        got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        for mine, theirs in zip(got, (P.beats_all(case) for case in cases)):
            self.assertAlmostEqual(mine, theirs, places=12)

    def test_the_default_style_keeps_its_own_test(self):
        adv = go("T9o", 25, "BB", "CO raise 3bb")
        self.assertNotIn("bb_realised", adv.data)
        self.assertIn("for how this hand plays after the flop", " ".join(adv.numbers))

    def test_the_tight_style_is_the_default_rows_with_the_guides_big_blind(self):
        self.assertEqual(R.STYLES, ("tag", "win", "tight"))
        for nb in range(8, 0, -1):
            default = R.rfi_range(nb, 40)
            with R.use_style("tight"):
                self.assertEqual(R.rfi_range(nb, 40), default, nb)
                for hero in range(nb - 1, -1, -1):
                    tight = R.vs_open_chart(nb, hero)
            for hero in range(nb - 1, -1, -1):
                with R.use_style("tight"):
                    tight = R.vs_open_chart(nb, hero)
                self.assertEqual(tight, R.vs_open_chart(nb, hero), (nb, hero))
        # away from the big blind the two answer alike
        for hand, stack, pos, facing in (("AJs", 40, "BTN", "CO raise 2.2bb"), ("77", 30, "CO", ""), ("KQo", 20, "SB", "BTN raise 2bb")):
            default = go(hand, stack, pos, facing)
            with R.use_style("tight"):
                self.assertEqual(go(hand, stack, pos, facing).action, default.action, (hand, pos))

    def test_the_page_works_the_share_out_as_the_engine_does(self):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        script = ("global.window = {}; global.document = {readyState: 'loading', addEventListener() {}};"
                  f"require({json.dumps(os.path.join(GUIDE, 'guide.js'))});"
                  "const out = []; for (const stack of [10, 25, 40, 100]) for (const last of [false, true]) for (let h = 0; h < 169; h++)"
                  " out.push(window.MenloGuide.realised(h, stack, last)); console.log(JSON.stringify(out));")
        got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        want = [P.bb_realised(h, stack, last) for stack in (10, 25, 40, 100) for last in (False, True) for h in range(169)]
        self.assertEqual(len(got), len(want))
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=9)


class WiderInPosition(unittest.TestCase):
    """The looser style's chart against a raise: more calls and re-raises from the cutoff and the button."""

    def tearDown(self):
        R.set_style("tag")

    def test_every_hand_of_the_tight_chart_is_in_the_looser_one(self):
        for opener in range(8, 0, -1):
            for hero in range(opener - 1, -1, -1):
                tight = R.vs_open_chart(opener, hero)
                with R.use_style("win"):
                    loose = R.vs_open_chart(opener, hero)
                for h in range(169):
                    if max(tight[k][h] for k in tight) >= 0.5:
                        self.assertGreaterEqual(max(loose[k][h] for k in loose), 0.5, (opener, hero, HANDS[h]))
                self.assertEqual(loose["value"], tight["value"], (opener, hero))     # what is re-raised for value does not change

    def test_it_is_wider_on_the_button_and_the_cutoff_and_about_half_way_to_a_solver(self):
        def width(chart):
            return range_pct([max(chart[k][h] for k in chart) for h in range(169)])
        tight = width(R.vs_open_chart(7, 2))
        with R.use_style("win"):
            button, cutoff, hijack = (width(R.vs_open_chart(7, hero)) for hero in (2, 3, 4))
            against_cutoff = width(R.vs_open_chart(3, 2))
            blind = R.vs_open_chart(7, 0)
        self.assertTrue(8 < tight < 10 and 12 < button < 15, (tight, button))        # a solver: about 25% (button, 100bb)
        self.assertEqual(button, cutoff)
        self.assertLess(hijack, button)
        self.assertTrue(18 < against_cutoff < 23, against_cutoff)
        self.assertEqual(blind, R.vs_open_chart(7, 0))                               # the big blind's row is not the chart's to widen

    def test_the_button_calls_a_first_seat_raise_with_more_hands(self):
        self.assertEqual(go("KJs", 60, "BTN", "UTG raise 2.2bb").action, "FOLD")
        with R.use_style("win"):
            self.assertEqual(go("KJs", 60, "BTN", "UTG raise 2.2bb").action, "CALL")
            self.assertEqual(go("AQo", 60, "CO", "UTG raise 2.2bb").action, "CALL")
            self.assertEqual(go("KJs", 60, "HJ", "UTG raise 2.2bb").action, "FOLD")
            self.assertTrue(go("AKs", 60, "BTN", "UTG raise 2.2bb").action.startswith("3-BET"))


def tables():
    path = os.path.join(GUIDE, "data.js")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        text = fh.read()
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


@unittest.skipUnless(tables() and not tables().get("quick") and not tables().get("partial"), "guide/data.js is not built")
class Tables(unittest.TestCase):
    """guide/data.js, as it is in the repository."""

    @classmethod
    def setUpClass(cls):
        cls.d = tables()

    def tearDown(self):
        R.set_style("tag")

    def table(self, family, style, opp, key):
        return self.d["tables"][self.d["index"][family][style][opp][",".join(str(k) for k in key)]]

    def test_every_spot_of_every_family_is_there_for_every_style_and_opponent(self):
        self.assertEqual(self.d["version"], B.VERSION)
        self.assertEqual((self.d["hands"], self.d["codes"], self.d["close"]), (list(HANDS), B.CODES, B.CLOSE))
        self.assertEqual(self.d["styles"], list(B.STYLES))
        self.assertEqual(self.d["opponents"], list(B.OPPONENTS))
        for name, (_, make) in B.FAMILIES.items():
            want = {",".join(str(k) for k in key) for key, _ in make()}
            for style in B.STYLES:
                for opp in B.OPPONENTS:
                    self.assertEqual(set(self.d["index"][name][style][opp]), want, (name, style, opp))

    def test_no_table_has_a_pair_folding_where_a_lower_pair_plays(self):
        for t in self.d["tables"]:
            a = B.unpack(t["a"])
            plays = [a[14 * i] not in "fF" for i in range(13)]
            self.assertEqual(plays, sorted(plays, reverse=True), a)

    def test_a_table_is_169_letters_and_its_range_169_marks(self):
        letters = set(B.CODES + B.CLOSE)
        for t in self.d["tables"]:
            a = B.unpack(t["a"])
            self.assertEqual(len(a), 169)
            self.assertLessEqual(set(a), letters)
            v = t.get("f", {}).get("v")
            if v is not None:
                self.assertRegex(self.d["ranges"][v], r"^[01]{169}$")
        self.assertEqual(len(set(json.dumps(t, sort_keys=True) for t in self.d["tables"])), len(self.d["tables"]))

    def test_the_tables_are_what_the_engine_answers_today(self):
        """A sample of spots asked again.  If this fails the engine has changed: build the tables again."""
        rng = random.Random(11)
        slow = {"two_allin"}                                    # dealt-out boards: 12 seconds a spot
        for name, (_, make) in B.FAMILIES.items():
            if name in slow:
                continue
            spots = list(make())
            for key, question in rng.sample(spots, 2 if len(spots) > 1 else 1):
                style, opp = rng.choice(B.STYLES), rng.choice(B.OPPONENTS)
                R.set_style(style)
                made = B.table(opp=opp, **question)
                kept = self.table(name, style, opp, key)
                self.assertEqual(B.unpack(kept["a"]), made["a"], (name, key, style, opp))
                self.assertEqual(kept.get("z"), made.get("z"), (name, key, style, opp))

    def test_all_ins_of_twenty_big_blinds_or_less_are_the_exact_solution(self):
        """Read from poker_coach/short.py: calling one all-in or two at every such stack, and first in up to
        10bb, where every hand is an all-in or a fold.  (Deeper, first in has small raises as well: there the
        table is the engine's, and an all-in in it is one the exact number makes.)"""
        from poker_coach import short as S
        self.assertEqual(S.top(), 20.0)
        rng = random.Random(3)
        for _ in range(90):
            stack = rng.choice([s for s in B.STACKS if s <= S.top()])
            hero = rng.randrange(0, 8)                               # players behind you
            kind = rng.choice(("open", "allin", "two"))
            if kind == "open" and hero >= 1:
                t, evs = self.table("open", "win", "unknown", (hero, stack)), S.node(stack, 8 - hero, 0)
                played = "aA"
                if stack > 10:
                    letters = B.unpack(t["a"])
                    self.assertNotIn("x", t.get("f", {}), (hero, stack))
                    self.assertEqual([HANDS[h] for h in range(169) if letters[h] in played and evs[h] <= 0], [], (hero, stack))
                    continue
            elif kind == "allin" and hero <= 7:
                first = rng.randrange(hero + 1, 9)
                t, evs = self.table("allin", "win", "unknown", (first, hero, stack)), S.node(stack, 8 - hero, 1 << (8 - first))
                played = "cCaAiIjJkK"
            elif kind == "two" and hero <= 6:
                first = rng.randrange(hero + 2, 9)
                t = self.table("two_short", "win", "unknown", (first, hero, stack))
                evs = S.node(stack, 8 - hero, (1 << (8 - first)) | (1 << (9 - first)))
                played = "cCaA"
            else:
                continue
            self.assertEqual(t["f"].get("x"), 1, (kind, hero, stack))
            self.assertNotIn("need", t["f"])
            letters = B.unpack(t["a"])
            wrong = [h for h in range(169) if (letters[h] in played) != (evs[h] > 0) and h % 14 != 0]      # pairs are put in order
            if stack <= 10:
                self.assertEqual([HANDS[h] for h in wrong], [], (kind, hero, stack))
            else:
                # above ten big blinds a player with no read moves in with a little less than the solved game's
                # range: a few calls near the edge are folds, and none the other way
                self.assertEqual([HANDS[h] for h in wrong if letters[h] in played and evs[h] < -0.1], [], (kind, hero, stack))
                self.assertEqual([HANDS[h] for h in wrong if abs(evs[h]) > 1.5], [], (kind, hero, stack))
                self.assertLess(sum(B.COMBO_COUNT[h] for h in wrong), 0.08 * 1326, (kind, hero, stack))
        # one stack deeper the engine answers by itself
        self.assertNotIn("x", self.table("allin", "win", "unknown", (3, 0, 22)).get("f", {}))
        self.assertIn("need", self.table("allin", "win", "unknown", (3, 0, 22))["f"])
        # the opponents choice does not move the all-ins first in; it moves the calls (the hands an all-in player holds)
        calls = lambda letters: sum(c for c, ch in zip(B.COMBO_COUNT, B.unpack(letters)) if ch in "cC")      # noqa: E731
        for opp in ("tight", "loose"):
            self.assertEqual(self.table("open", "win", opp, (5, 4))["a"], self.table("open", "win", "unknown", (5, 4))["a"])
        tight, usual, loose = (calls(self.table("allin", "win", opp, (3, 2, 5))["a"]) for opp in ("tight", "unknown", "loose"))
        self.assertLess(tight, usual)
        self.assertLess(usual, loose)

    def test_on_the_bubble_an_exact_call_keeps_only_the_hands_with_points_to_spare(self):
        """The Bubble stage asks 10 points of equity more of a call.  A table of the exact solution has no one
        number to add them to, so it marks the calls that have them, and the page folds the others."""
        import shutil
        with open(os.path.join(GUIDE, "guide.js")) as fh:
            self.assertIn(f"const BUBBLE_POINTS = {B.BUBBLE:.2f};", fh.read())
        for family, key, pos, facing in (("allin", (2, 0, 6), "BB", "BTN allin"), ("allin", (8, 2, 12), "BTN", "UTG allin"),
                                         ("two_short", (5, 0, 8), "BB", "LJ allin, HJ allin")):
            t = self.table(family, "win", "unknown", key)
            self.assertEqual(t["f"].get("x"), 1, key)
            letters, keep = B.unpack(t["a"]), B.unmask(t["f"]["bk"])
            self.assertEqual([HANDS[h] for h in range(169) if keep[h] and letters[h] in "fF"], [], key)      # only calls are kept
            self.assertTrue(any(keep), key)
            self.assertTrue(any(not keep[h] and letters[h] in "cC" for h in range(169)), key)       # and some calls are not
            spot = P.quick_spot(0, None, float(key[-1]), 9, pos, facing)
            for h in random.Random(4).sample(range(169), 25):
                if h % 14 == 0:
                    continue                                    # pairs are put in order
                adv = P.advise(dataclasses.replace(spot, hand=h))
                self.assertEqual(keep[h], adv.data["exact_edge"] >= B.BUBBLE, (key, HANDS[h]))
                # the points are the exact answer over the pot the call plays for
                self.assertEqual(adv.data["exact_edge"] > 0, adv.data["exact_ev"] > 0, (key, HANDS[h]))
        # a deeper all-in, which the engine prices by itself, keeps its one number for the page to add to
        deep = self.table("allin", "win", "unknown", (2, 0, 25))["f"]
        self.assertIn("need", deep)
        self.assertNotIn("bk", deep)
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        t = self.table("allin", "win", "unknown", (2, 0, 6))
        letters, keep = B.unpack(t["a"]), B.unmask(t["f"]["bk"])
        lost = next(h for h in range(169) if letters[h] == "c" and not keep[h])
        kept = next(h for h in range(169) if letters[h] == "c" and keep[h])
        spot = {"players": 9, "seat": 0, "stack": 6, "line": "allin", "from": 2}
        cases = [(dict(spot, stage="bubble"), HANDS[lost]), (dict(spot, stage="bubble"), HANDS[kept]), (spot, HANDS[lost])]
        got = [mine["name"] for mine in self.node_answers(cases)]
        self.assertEqual(got, ["FOLD", "CALL", "CALL"], (HANDS[lost], HANDS[kept]))

    def test_first_in_tables_say_how_often_an_all_in_gets_through(self):
        for style in B.STYLES:
            for nb in range(1, 9):
                for stack in B.STACKS:
                    f = self.table("open", style, "unknown", (nb, stack)).get("f", {})
                    if stack <= 20:
                        self.assertIn("fe", f, (style, nb, stack))
                        self.assertTrue(0.0 <= f["fe"] <= 1.0)
                    if stack >= 28:
                        self.assertNotIn("fe", f, (style, nb, stack))
        # a deeper stack gets through more often.  A later seat does not: the first seat has more players
        # behind, but against its few hands each of them calls with far fewer (58% and 56% with 12bb)
        get = lambda nb, stack: self.table("open", "win", "unknown", (nb, stack))["f"]["fe"]      # noqa: E731
        self.assertLess(get(2, 4), 0.05)                     # with 4bb the big blind nearly always calls
        self.assertLess(get(2, 8), get(2, 12))
        self.assertLess(get(2, 12), get(2, 20))
        self.assertLess(abs(get(8, 12) - get(2, 12)), 0.12)
        self.assertTrue(0.35 < get(2, 12) < 0.7, get(2, 12))

    def test_small_tables_have_tables_of_their_own_where_the_answer_is_exact(self):
        """Three to six players: "family@players", read from that table's own solution."""
        from poker_coach import short as S
        self.assertEqual(self.d["short"], {"top": S.top(), "tables": [3, 4, 5, 6]})
        self.assertEqual(B.SMALL, (3, 4, 5, 6))
        for n in B.SMALL:
            for name in B.SIZED:
                self.assertIn(f"{name}@{n}", self.d["index"], (name, n))
            keys = set(self.d["index"][f"open@{n}"]["win"]["unknown"])
            self.assertEqual(keys, {f"{nb},{s}" for nb in range(1, n) for s in B.STACKS if s <= S.top()}, n)
        # the big blind against a button all-in of 5bb: at six players he calls with more hands than at nine,
        # where six players have folded their middle cards (and the table says which solution it is)
        six = B.unpack(self.table("allin@6", "win", "unknown", (2, 0, 5))["a"])
        nine = B.unpack(self.table("allin", "win", "unknown", (2, 0, 5))["a"])
        calls = lambda letters: sum(c for c, ch in zip(B.COMBO_COUNT, letters) if ch in "cC") / 13.26      # noqa: E731
        self.assertGreater(calls(six), calls(nine) + 5)
        evs = S.node(5, 5, 1 << 3, 6)
        wrong = [HANDS[h] for h in range(169) if (six[h] in "cC") != (evs[h] > 0) and h % 14 != 0]
        self.assertEqual(wrong, [])
        # against a raise only the sizes that commit the raiser are kept apart; the others are the family's own
        for key in self.d["index"]["vsraise@6"]["win"]["unknown"]:
            o, h, callers, zi, stack = (int(x) for x in key.split(","))
            self.assertTrue(callers == 0 and B.RAISE_SIZES[zi] >= B.COMMITS * stack and stack <= S.top() and o < 6, key)

    def test_the_page_reads_a_small_tables_own_tables(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        # the spot as the page has it, the hand, the tables it must be read from, and whether they are the exact solution
        cases = [({"players": 6, "seat": 2, "stack": 5, "line": "open"}, "K9o", "open@6", True),
                 ({"players": 8, "seat": 2, "stack": 5, "line": "open"}, "K9o", "open", True),
                 ({"players": 9, "seat": 2, "stack": 5, "line": "open"}, "K9o", "open", True),
                 ({"players": 6, "seat": 2, "stack": 12, "line": "open"}, "K9o", "open@6", False),
                 ({"players": 6, "seat": 2, "stack": 22, "line": "open"}, "K9o", "open", False),
                 ({"players": 6, "seat": 0, "stack": 16, "line": "allin", "from": 2}, "A7o", "allin@6", True),
                 ({"players": 6, "seat": 0, "stack": 25, "line": "allin", "from": 2}, "A7o", "allin", False),
                 ({"players": 3, "seat": 0, "stack": 4, "line": "allin", "from": 2}, "T7o", "allin@3", True),
                 ({"players": 5, "seat": 0, "stack": 6, "line": "two_allin", "from": 3}, "A8s", "two_short@5", True),
                 ({"players": 9, "seat": 2, "stack": 6, "line": "two_allin", "from": 6}, "A8s", "two_short", True),
                 ({"players": 9, "seat": 2, "stack": 14, "line": "two_allin", "from": 6}, "A8s", "two_short", True),
                 ({"players": 9, "seat": 0, "stack": 25, "line": "two_allin", "from": 5}, "A8s", "two_allin", False),
                 ({"players": 6, "seat": 0, "stack": 4, "line": "raise", "from": 3, "size": 0}, "Q7s", "vsraise@6", True),
                 ({"players": 6, "seat": 0, "stack": 9, "line": "raise", "from": 3, "size": 0}, "Q7s", "vsraise", False),
                 ({"players": 4, "seat": 1, "stack": 5, "line": "limp"}, "K8o", "limp@4", True)]
        for (st, hand, where, exact), mine in zip(cases, self.node_answers(cases)):
            self.assertEqual(mine["from"], where, (st, hand))
            self.assertEqual(mine["exact"], exact, (st, hand))
            letters = B.unpack(self.table(where, "win", "unknown", mine["key"])["a"])
            self.assertEqual(B.ACTIONS[(B.CODES + B.CLOSE).index(letters[HANDS.index(hand)]) % len(B.CODES)], mine["name"], (st, hand))

    def test_one_hand_at_every_stack_and_the_sheet_are_the_tables(self):
        """The strip under the answer and the "Every stack" sheet: read from the same tables, stack by stack."""
        import shutil
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        import subprocess
        spots = [({"players": 9, "seat": 2, "line": "open"}, "K9o"), ({"players": 9, "seat": 8, "line": "open"}, "A5s"),
                 ({"players": 9, "seat": 0, "line": "allin", "from": 2}, "Q8o"), ({"players": 6, "seat": 1, "line": "open"}, "T6s"),
                 ({"players": 9, "seat": 1, "line": "raise", "from": 3}, "A9o")]
        got = self.node_call(f"{json.dumps(spots)}.map(([st, hand]) => window.MenloGuide.everyStack(st, hand))")
        for (st, hand), mine in zip(spots, got):
            plays = mine["plays"]
            self.assertGreater(len(plays), 10, (st, hand))
            self.assertEqual([p["stack"] for p in plays], sorted(p["stack"] for p in plays))
            # the stretches are the plays, joined where the play is the same, in order and without holes
            self.assertEqual(mine["runs"][0]["from"], plays[0]["stack"])
            self.assertEqual(mine["runs"][-1]["to"], plays[-1]["stack"])
            for run in mine["runs"]:
                inside = [p["name"] for p in plays if run["from"] <= p["stack"] <= run["to"]]
                self.assertTrue(inside and all(self.label(n) == self.label(run["name"]) for n in inside), (st, hand, run, inside))
            # the sheet's number: the deepest stack at which the hand still goes in for everything.  That is an
            # all-in, a call of an all-in, and in a table of the exact solution any play that is not a fold
            for p in plays:
                want = p["name"] in ("ALLIN", "RAISE_CALL", "ISOLATE_ALLIN") \
                    or (p["name"] in ("CALL", "ISOLATE") and (st["line"] == "allin" or p["exact"]))
                self.assertEqual(p["in"], want, (st, hand, p))
            self.assertEqual(mine["sheet"]["top"], max([p["stack"] for p in plays if p["in"]], default=0), (st, hand))
            below = [p["in"] for p in plays if p["stack"] < mine["sheet"]["top"]]
            self.assertEqual(mine["sheet"]["gap"], not all(below), (st, hand))

    @staticmethod
    def label(name):
        return {"LIMP": "CALL", "ISOLATE": "RERAISE", "ISOLATE_ALLIN": "ALLIN"}.get(name, name)

    def node_call(self, expression):
        """An expression of the page's script with the tables loaded, in node; its value."""
        import subprocess
        script = (
            "const fs = require('fs'); global.window = {};"
            "const el = () => ({innerHTML: '', addEventListener() {}, classList: {toggle() {}}, getBoundingClientRect: () => ({height: 52}), dataset: {}, setAttribute() {}});"
            "const made = {};"
            "global.document = {readyState: 'complete', addEventListener() {}, getElementById: (id) => (made[id] = made[id] || el()), querySelector: () => null, querySelectorAll: () => [], activeElement: null, documentElement: {scrollTop: 0}};"
            "global.localStorage = {getItem: () => null, setItem() {}}; global.window.addEventListener = () => {}; global.window.scrollTo = () => {}; global.atob = (t) => Buffer.from(t, 'base64').toString('binary');"
            f"eval(fs.readFileSync({json.dumps(os.path.join(GUIDE, 'data.js'))}, 'utf8').replace('window.GUIDE_DATA', 'global.window.GUIDE_DATA'));"
            f"require({json.dumps(os.path.join(GUIDE, 'guide.js'))});"
            f"console.log(JSON.stringify({expression}));")
        return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)

    def node_answers(self, cases):
        """The page's own reading of spots, without a browser."""
        return self.node_call(f"{json.dumps([[c[0], c[1]] for c in cases])}.map(([st, hand]) => window.MenloGuide.answer(st, hand))")

    def test_two_all_ins_this_short_have_a_table_for_every_seat(self):
        from poker_coach import short as S
        keys = set(self.d["index"]["two_short"]["win"]["unknown"])
        want = {f"{o},{h},{s}" for o in range(8, 1, -1) for h in range(o - 2, -1, -1) for s in B.STACKS if s <= S.top()}
        self.assertEqual(keys, want)
        # the big blind has two of his three big blinds in and calls with everything; the button has nothing in
        bb = B.unpack(self.table("two_short", "win", "unknown", (8, 0, 3))["a"])
        btn = B.unpack(self.table("two_short", "win", "unknown", (8, 2, 3))["a"])
        self.assertGreater(sum(1 for ch in bb if ch in "cC"), 160)
        self.assertLess(sum(1 for ch in btn if ch in "cC"), 60)

    def test_the_tables_against_a_raise_are_todays_and_carry_the_big_blinds_price(self):
        """A larger sample of the spots that changed with the size of the raise: the big blind at every depth, and
        the other seats where the stack is short."""
        rng = random.Random(7)
        spots = list(B.fam_vsraise())
        blind = rng.sample([spot for spot in spots if spot[0][1] == 0], 10)
        short = rng.sample([spot for spot in spots if spot[0][1] >= 1 and spot[0][4] <= 12], 8)
        for key, question in blind + short:
            style, opp = rng.choice(B.STYLES), rng.choice(B.OPPONENTS)
            R.set_style(style)
            made = B.table(opp=opp, **question)
            kept = self.table("vsraise", style, opp, key)
            self.assertEqual(B.unpack(kept["a"]), made["a"], (key, style, opp))
            facts = kept.get("f", {})
            size, stack = B.RAISE_SIZES[key[3]], key[4]
            if key[1] == 0 and size < B.COMMITS * stack:          # a raise the raiser can still fold: the page shows the test
                self.assertEqual(facts["m"], P._BB_MARGIN[style], (key, style))
                self.assertAlmostEqual(facts["p"], B.bb_price("vsraise", key)["p"], msg=str(key))
                self.assertEqual(facts.get("ip", 0), 1 if key[0] == 1 and key[2] == 0 else 0, key)
                self.assertRegex(self.d["ranges"][facts["v"]], r"^[01]{169}$")
                # the callers' hands, for the equity against all of them
                self.assertEqual(len(facts.get("cv", [])), key[2], key)
                for k, v in enumerate(facts.get("cv", []), start=1):
                    R.set_style(style)
                    marks = "".join("1" if w >= 0.5 else "0" for w in P.flat_range(key[0], key[0] - k))
                    self.assertEqual(self.d["ranges"][v], marks, (key, k))
            else:                                                 # another seat, or a raise priced as an all-in
                self.assertNotIn("p", facts, key)
        for key, question in rng.sample(list(B.FAMILIES["hu_vsraise"][1]()), 4):
            style = rng.choice(B.STYLES)
            R.set_style(style)
            self.assertEqual(B.unpack(self.table("hu_vsraise", style, "unknown", key)["a"]), B.table(opp="unknown", **question)["a"], key)
        # heads-up the raiser is the button, who raises most hands: the page is given that range for the numbers
        # under the big blind's answer (it once got none, and showed nothing there)
        for key, _question in B.FAMILIES["hu_vsraise"][1]():
            if B.RAISE_SIZES[key[0]] < B.COMMITS * key[-1]:
                facts = self.table("hu_vsraise", "win", "unknown", key).get("f", {})
                self.assertIn("v", facts, key)
                self.assertAlmostEqual(range_pct([float(c) for c in self.d["ranges"][facts["v"]]]), 80, delta=2, msg=str(key))
        self.assertEqual(self.d["sizes"], {"raise": list(B.RAISE_SIZES), "reraise": list(B.RERAISE_TIMES), "commit": B.COMMITS})
        self.assertEqual(self.d["usual"], json.loads(json.dumps(B.usual_sizes())))

    def test_a_bigger_raise_is_never_called_with_more_hands_by_the_big_blind(self):
        """Every big blind table against a raise, beside the same spot one size up.  (Not across the size that
        commits the raiser: from there the raise is priced as an all-in, with the hands that move all-in.)"""
        def folds(tid):
            return range_pct([1.0 if ch in "fF" else 0.0 for ch in B.unpack(self.d["tables"][tid]["a"])])
        seen = 0
        for style in B.STYLES:
            for opp in B.OPPONENTS:
                index = self.d["index"]["vsraise"][style][opp]
                for key, tid in index.items():
                    o, h, callers, zi, stack = (int(x) for x in key.split(","))
                    bigger = index.get(f"{o},{h},{callers},{zi + 1},{stack}")
                    if h or callers or bigger is None or B.RAISE_SIZES[zi + 1] >= B.COMMITS * stack:
                        continue
                    seen += 1
                    self.assertGreaterEqual(folds(bigger), folds(tid) - 2.5, (style, opp, key))
        self.assertGreater(seen, 3000)

    def test_the_numbers_the_page_works_equity_out_of(self):
        import base64
        eq = base64.b64decode(self.d["eq"])
        pairs = base64.b64decode(self.d["pairs"])
        self.assertEqual((len(eq), len(pairs)), (169 * 169, 169 * 169))
        aa, kk, aks, sevens = HANDS.index("AA"), HANDS.index("KK"), HANDS.index("AKs"), HANDS.index("72o")
        self.assertAlmostEqual(eq[aa * 169 + kk] / 250, 0.82, delta=0.015)
        self.assertAlmostEqual(eq[kk * 169 + aa] / 250, 0.18, delta=0.015)
        self.assertAlmostEqual(eq[aks * 169 + sevens] / 250, 0.68, delta=0.03)
        self.assertEqual(pairs[aa * 169 + kk], 36)              # six aces against six kings
        self.assertEqual(pairs[aa * 169 + aa], 6)               # the other two aces, once for each of mine
        self.assertEqual(pairs[aks * 169 + aks], 12)

    def test_the_looser_style_plays_more_hands_first_in_and_no_spot_is_empty(self):
        def playing(t):
            a = B.unpack(t["a"])
            return sum(1 for ch in a if ch not in "fF")
        for nb in (8, 5, 3, 2):
            for stack in (15, 30, 60):
                self.assertGreaterEqual(playing(self.table("open", "win", "unknown", (nb, stack))),
                                        playing(self.table("open", "tight", "unknown", (nb, stack))), (nb, stack))
        for name in self.d["index"]:
            for key, tid in self.d["index"][name]["win"]["unknown"].items():
                a = B.unpack(self.d["tables"][tid]["a"])
                self.assertNotIn(a[0], "fF", (name, key, "aces are folded"))


class Speed(unittest.TestCase):
    """Regular, turbo, hyper: the play is the same, what folding costs is not."""

    def node(self, body):
        import shutil
        import subprocess
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        script = ("global.window = {}; global.document = {readyState: 'loading', addEventListener() {}};"
                  f"require({json.dumps(os.path.join(GUIDE, 'guide.js'))});" + body)
        return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_the_speeds_are_the_tournament_models(self):
        from poker_coach import latereg as L
        got = self.node("console.log(JSON.stringify(window.MenloGuide.SPEED));")
        self.assertEqual(list(got), ["regular", "turbo", "hyper"])
        for name, sp in got.items():
            self.assertEqual((sp["hands"], sp["growth"]), (L.SPEEDS[name]["hands_per_level"], L.SPEEDS[name]["growth"]), name)

    def test_the_pages_clock_is_the_models_sum(self):
        from poker_coach import latereg as L
        cases = [(stack, players, seat, speed) for stack in (2, 4.5, 8, 12, 25, 60) for players in (2, 3, 6, 8, 9)
                 for seat in range(players) for speed in ("regular", "turbo", "hyper")]
        got = self.node(f"console.log(JSON.stringify({json.dumps(cases)}.map((c) => window.MenloGuide.clock(...c))));")
        for case, mine in zip(cases, got):
            want = L.fold_clock(*case)
            self.assertEqual(mine["hands"], want["hands"], case)
            self.assertEqual(mine["gone"], want["gone"], case)
            self.assertAlmostEqual(mine["atBlind"], want["at_blind"], places=9, msg=str(case))
            self.assertAlmostEqual(mine["orbit"], want["orbit"], places=9, msg=str(case))

    def test_what_the_clock_says(self):
        from poker_coach import latereg as L
        # the big blind is next for the first seat, a whole round away for the big blind itself
        self.assertEqual(L.fold_clock(12, 8, 7, "turbo")["hands"], 1)
        self.assertEqual(L.fold_clock(12, 8, 1, "turbo")["hands"], 7)
        self.assertEqual(L.fold_clock(12, 8, 0, "turbo")["hands"], 0)
        # a round costs the two blinds and the ante, and the faster the blinds the less is left
        orbits = [L.fold_clock(12, 8, 2, speed)["orbit"] for speed in ("regular", "turbo", "hyper")]
        self.assertTrue(12 - 2.5 > orbits[0] > orbits[1] > orbits[2] > 4, orbits)
        self.assertAlmostEqual(orbits[2], 5.3, delta=0.1)               # 12bb on the button of a hyper: 5.3bb a round later
        # before the blinds are paid only the level has moved
        self.assertAlmostEqual(L.fold_clock(12, 8, 2, "hyper")["at_blind"], 12 / L.level_ahead(6, "hyper"), places=9)
        # two big blinds do not last a round anywhere
        self.assertTrue(L.fold_clock(2, 8, 7, "regular")["gone"])
        self.assertEqual(L.fold_clock(2, 8, 7, "regular")["orbit"], 0.0)

    def test_the_clock_is_the_average_of_the_models_levels(self):
        """Level by level with the model's own blinds, over every place in a level the table can be at."""
        from poker_coach import latereg as L
        for speed in ("regular", "turbo", "hyper"):
            sp = L.SPEEDS[speed]
            for seat in (0, 2, 5, 7):
                outs = []
                for step in range(100):
                    blinds = L.Blinds(sp["growth"], sp["hands_per_level"], (step + 0.5) / 100, ())
                    outs.append((12 - L.fold_cost(8, blinds, 8, seat, "bb")) / blinds.mult(8))
                self.assertAlmostEqual(sum(outs) / len(outs), L.fold_clock(12, 8, seat, speed)["orbit"], delta=0.1, msg=f"{speed} {seat}")


class PageFiles(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(GUIDE, name)) as fh:
            return fh.read()

    def test_the_speed_choice_changes_no_answer(self):
        """Read from the script: the table is found without the speed, and the clock and the sheet are its own parts."""
        js = self.read("guide.js")
        lookup = js[js.index("function lookup(st, over)"):js.index("function answers(res, st)")]
        self.assertNotIn("speed", lookup)
        answers = js[js.index("function answers(res, st)"):js.index("const KIND =")]
        self.assertNotIn("speed", answers)
        for part in ('id="clock"', 'id="strip"', "function clockHtml(st)", "function sheetHtml(st, res)", 'chipRow(Object.keys(SPEED)'):
            self.assertIn(part, js, part)
        self.assertIn('speed: "regular", sheet: false', js)
        css = self.read("guide.css")
        for rule in ("#clock{order:3}", "#strip{order:5}", ".cols section:empty{display:none}"):
            self.assertIn(rule, css, rule)

    def test_the_page_asks_nobody_for_anything(self):
        """Styles, script, fonts and tables are files beside the page."""
        html = self.read("index.html")
        for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
            if ref.startswith("data:"):
                continue
            self.assertNotRegex(ref, r"^(https?:)?//", ref)
            name = ref.split("?")[0]
            if name != "data.js":                      # made by tools/build_guide.py
                self.assertTrue(os.path.exists(os.path.join(GUIDE, name)), ref)
        for name in ("guide.js", "guide.css", "fonts.css"):
            self.assertNotRegex(self.read(name), r"https?://", name)
        for ref in re.findall(r"url\(([^)]+)\)", self.read("fonts.css")):
            self.assertTrue(os.path.exists(os.path.join(GUIDE, ref)), ref)

    def test_a_new_page_or_new_tables_are_asked_for_by_number(self):
        """A browser keeps files it has seen: the page names its script, styles and tables with their numbers,
        and the script refuses tables from before the sizes were in the keys."""
        html, js = self.read("index.html"), self.read("guide.js")
        page = int(re.search(r"const PAGE = (\d+);", js).group(1))
        oldest = int(re.search(r"const TABLES = (\d+);", js).group(1))
        self.assertEqual(re.findall(r'"(guide\.js|guide\.css|data\.js)\?v=(\d+)"', html),
                         [("guide.css", str(page)), ("data.js", str(B.VERSION)), ("guide.js", str(page))])
        self.assertEqual(oldest, B.VERSION)
        self.assertIn("(data.version || 1) < TABLES", js)

    def test_the_bar_with_next_hand_stays_at_the_top_of_the_window(self):
        """Read from the files: the browser run checks at every step that the button is in sight."""
        css, js = self.read("guide.css"), self.read("guide.js")
        self.assertRegex(css, r"\.top\{position:sticky;top:0;")
        self.assertIn("height:calc(52px + env(safe-area-inset-top,0px))", css)
        self.assertIn("const BAR = 52;", js)                           # what the script takes the bar's height to be, until it measures it
        # under a phone's status bar the page starts below the strip and the bar reaches up over it, once
        self.assertIn(":root{padding-top:env(safe-area-inset-top,0px)}", css)
        self.assertIn("margin:calc(-1 * env(safe-area-inset-top,0px)) calc(-1 * var(--gr)) 0 calc(-1 * var(--gl))", css)
        header = js[js.index('<header class="top" id="top">'):js.index("</header>")]
        for part in ('class="brand"', 'id="mini"', 'id="btn-reset"', 'id="btn-next"'):
            self.assertIn(part, header)
        self.assertNotIn('id="mini"', js[js.index("</header>"):])       # the answer in one line is in the bar, nowhere else
        self.assertIn('.top.away:not(.post) #mini{display:flex}', css)

    def test_the_page_knows_every_family_of_the_builder(self):
        js = self.read("guide.js")
        for name in B.FAMILIES:
            self.assertIn(f'"{name.split("@")[0]}"', js, name)       # "open@6": the family "open" at a table of six
        self.assertIn('fam + "@" + n', js)
        for action in B.ACTIONS:
            self.assertIn(action, js, action)

    def test_the_map_gives_every_line_its_seats_and_reset_goes_back_to_the_start(self):
        """Read from the script: the browser run checks what they do."""
        js = self.read("guide.js")
        lines = re.findall(r'\{id: "(\w+)", group: \d', js)
        self.assertEqual(len(lines), 11)
        roles = js[js.index("function roles(st)"):js.index("const POD_TAG")]
        for line in lines:
            if line != "open":                     # nobody in: the seats before you folded, the rest wait
                self.assertIn(f'case "{line}"', roles, line)
        self.assertIn('data-act="reset"', js)
        self.assertIn("state = fresh();", js)
        self.assertIn("const fresh = () => JSON.parse(JSON.stringify(DEFAULTS));", js)

    def test_the_page_keeps_its_hands_off_the_table(self):
        """A lookup: it does not read a screen, press a button or hide from anything."""
        js = self.read("guide.js")
        for word in ("getDisplayMedia", "captureStream", "setContentProtection", "XMLHttpRequest", "WebSocket", "sendBeacon"):
            self.assertNotIn(word, js, word)
        # it fetches its own tables and nothing else: the tournament's, and the Spin & Go ones when that game is chosen
        self.assertEqual(sorted(re.findall(r"fetch\(([^)]*)\)", js)), ['"data.json"', '"spin.json"'])

    def test_the_one_file_page_for_publishing(self):
        page = build_guide_page.page()
        self.assertTrue(page.startswith("<title>Menlo Guide</title>"))
        for tag in ("!doctype", "html", "head", "body"):
            self.assertNotRegex(page.lower(), rf"<{tag}[\s>]", tag)
        outside = set(re.findall(r'(?:src|href)="(https?://[^"/]+)', page))
        self.assertLessEqual(outside, {"https://fonts.googleapis.com", "https://fonts.gstatic.com"})
        self.assertIn(self.read("guide.js"), page)
        self.assertIn(self.read("guide.css"), page)
        self.assertEqual(page.lower().count("<script"), 1)


if __name__ == "__main__":
    unittest.main()


def spin_tables():
    path = os.path.join(GUIDE, "spin.js")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        text = fh.read()
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


@unittest.skipUnless(spin_tables() and not spin_tables().get("quick"), "guide/spin.js is not built")
class SpinTables(unittest.TestCase):
    """guide/spin.js, as it is in the repository: the Spin & Go tables (tools/build_spin_guide.py)."""

    @classmethod
    def setUpClass(cls):
        import build_spin_guide as G
        cls.G = G
        cls.d = spin_tables()

    def tearDown(self):
        R.set_style("tag")

    def table(self, family, opp, key):
        return self.d["tables"][self.d["index"][family]["win"][opp][",".join(str(k) for k in key)]]

    def test_every_spot_of_every_family_is_there_for_every_opponent(self):
        from poker_coach import spin_exact as SX
        G, d = self.G, self.d
        self.assertEqual((d["version"], d["kind"], d["styles"]), (G.VERSION, "spin", ["win"]))
        self.assertEqual((d["hands"], d["codes"], d["close"]), (list(HANDS), B.CODES, B.CLOSE))
        self.assertEqual(d["opponents"], list(B.OPPONENTS))
        self.assertEqual((d["x"], d["y"], d["hu"]), (list(SX.x_grid()), list(SX.y_grid()), list(SX.hu_grid())))
        for name, (_, make) in G.FAMILIES.items():
            want = {",".join(str(k) for k in key) for key, _ in make(False)}
            for opp in B.OPPONENTS:
                self.assertEqual(set(d["index"][name]["win"][opp]), want, (name, opp))

    def test_a_table_is_169_letters_and_its_ranges_169_marks(self):
        letters = set(B.CODES + B.CLOSE)
        for t in self.d["tables"]:
            a = B.unpack(t["a"])
            self.assertEqual(len(a), 169)
            self.assertLessEqual(set(a), letters)
            f = t.get("f", {})
            for v in [f.get("v")] + list(f.get("cv", [])):
                if v is not None:
                    self.assertRegex(self.d["ranges"][v], r"^[01]{169}$")

    def test_no_table_has_a_pair_folding_where_a_lower_pair_plays(self):
        """Pairs marked close are left out: their numbers are within the noise of zero."""
        for t in self.d["tables"]:
            a = B.unpack(t["a"])
            plays = [a[14 * i] not in "fx" for i in range(13) if a[14 * i] not in B.CLOSE]
            self.assertEqual(plays, sorted(plays, reverse=True), a)

    def test_the_tables_are_what_the_engine_answers_today(self):
        """A sample of spots asked again.  If this fails the engine has changed: build the spin tables again."""
        G = self.G
        rng = random.Random(17)
        for name, (_, make) in G.FAMILIES.items():
            spots = list(make(False))
            for key, question in rng.sample(spots, 2 if len(spots) > 1 else 1):
                opp = rng.choice(B.OPPONENTS)
                R.set_style("win")
                made = G.table(opp=opp, **question)
                kept = self.table(name, opp, key)
                self.assertEqual(B.unpack(kept["a"]), made["a"], (name, key, opp))
                self.assertEqual(kept.get("z"), made.get("z"), (name, key, opp))

    def test_short_all_ins_are_the_exact_solution(self):
        """First in with 10bb or less every hand is an all-in or a fold, and it is the solved game's; calls of
        an all-in are the solved game's at every stack.  Close plays may fall either way."""
        from poker_coach import spin_exact as SX
        from poker_coach.cards import COMBO_COUNT
        G = self.G
        rng = random.Random(4)
        configs = [c for c in G.configs3() if c[2] <= 30]
        for _ in range(60):
            tok, st, x = rng.choice(configs)
            stacks = G.engine_stacks(st, 3)
            kind = rng.choice(("open", "allin"))
            if kind == "open":
                hero = rng.choice((2, 1))
                if x > 10:
                    continue
                t, evs, played = self.table("s_open", "unknown", (hero, tok)), SX.node(3, stacks, 2 - hero, 0), "aA"
            else:
                o, hero = rng.choice(((2, 1), (2, 0), (1, 0)))
                if G.behind(o, st) <= 0:
                    continue
                t = self.table("s_allin", "unknown", (o, hero, tok))
                # covering a short all-in with a player behind, the all-in is an isolating one (I)
                evs, played = SX.node(3, stacks, 2 - hero, 1 << (2 - o)), "cCaAiI"
            letters = B.unpack(t["a"])
            wrong = [HANDS[h] for h in range(169) if (letters[h] in played) != (evs[h] > 0)
                     and abs(evs[h]) >= SX.close(x) and letters[h] not in B.CLOSE]
            self.assertEqual(wrong, [], (kind, tok))
