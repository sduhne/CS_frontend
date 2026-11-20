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
            self.assertFalse(key[2] and key[3] <= 5, key)


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
                                        playing(self.table("open", "tag", "unknown", (nb, stack))), (nb, stack))
        for name in self.d["index"]:
            for key, tid in self.d["index"][name]["win"]["unknown"].items():
                a = B.unpack(self.d["tables"][tid]["a"])
                self.assertNotIn(a[0], "fF", (name, key, "aces are folded"))


class PageFiles(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(GUIDE, name)) as fh:
            return fh.read()

    def test_the_page_asks_nobody_for_anything(self):
        """Styles, script, fonts and tables are files beside the page."""
        html = self.read("index.html")
        for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
            if ref.startswith("data:"):
                continue
            self.assertNotRegex(ref, r"^(https?:)?//", ref)
            if ref != "data.js":                       # made by tools/build_guide.py
                self.assertTrue(os.path.exists(os.path.join(GUIDE, ref)), ref)
        for name in ("guide.js", "guide.css", "fonts.css"):
            self.assertNotRegex(self.read(name), r"https?://", name)
        for ref in re.findall(r"url\(([^)]+)\)", self.read("fonts.css")):
            self.assertTrue(os.path.exists(os.path.join(GUIDE, ref)), ref)

    def test_the_page_knows_every_family_of_the_builder(self):
        js = self.read("guide.js")
        for name in B.FAMILIES:
            self.assertIn(f'"{name}"', js, name)
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
        self.assertEqual(re.findall(r"fetch\(([^)]*)\)", js), ['"data.json"'])

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
