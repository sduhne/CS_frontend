"""Spins solved exactly: three players (or two), no ante, one prize, unequal stacks (poker_coach/spin_exact.py).

The data file is made by tools/build_spin_exact.py with the solver in tools/aof_solver.c.  Nothing here runs
the solver: the tests hold the stored answers to what any such solution must look like, and hold the engine
to them where the game is theirs.
"""
import json
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from poker_coach import preflop as P                           # noqa: E402
from poker_coach import ranges as R                            # noqa: E402
from poker_coach import spin_exact as SX                       # noqa: E402
from poker_coach.cards import COMBO_COUNT, HAND_INDEX, HANDS, parse_hand   # noqa: E402
from poker_coach.pushfold import HandSetup                     # noqa: E402

X_GRID = (2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30)
Y_GRID = (1, 1.5, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25)
HU_GRID = (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30)
NODES3 = {"0:0", "1:0", "1:1", "2:1", "2:2", "2:3"}       # who decides, with whom all-in before: every decision of three
NODES2 = {"0:0", "1:1"}
BTN, SB, BB = 0, 1, 2                                       # the engine's places at a table of three


def spin(stacks, hand, hero, facing="", opp=None):
    """The engine's answer in a spin: ``stacks`` in big blinds, button first (heads-up: small blind first)."""
    h, cards = parse_hand(hand)
    n = len(stacks)
    pos = ("BTN", "SB", "BB")[hero] if n == 3 else ("SB", "BB")[hero]
    spot = P.quick_spot(h, cards, stacks[hero], n, pos, facing, ante=False, stacks=list(stacks))
    if opp:
        spot.types = [opp] * n
    R.set_style("win")
    try:
        return P.advise(spot)
    finally:
        R.set_style("tag")


def setup(stacks, **kw):
    return HandSetup([float(s) for s in stacks], kw.get("sb", 0.5), 1.0, kw.get("ante", 0.0), kw.get("bb_ante", 0.0))


def first(action: str) -> str:
    return action.split()[0].upper()


@unittest.skipUnless(SX.available(), "poker_coach/data/spin_exact.json is missing: python3 tools/build_spin_exact.py --work DIR")
class Data(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "poker_coach", "data", "spin_exact.json")) as fh:
            cls.d = json.load(fh)

    def test_the_file_is_the_game_of_a_spin_and_whole(self):
        d = self.d
        self.assertEqual((d["sb"], d["bb"], d["ante"]), (0.5, 1, 0))
        self.assertEqual((d["train"], d["samples"], d["br_samples"]), (20_000_000, 50_000, 20_000))
        self.assertEqual((tuple(d["x"]), tuple(d["y"]), tuple(d["hu"])), (X_GRID, Y_GRID, HU_GRID))
        self.assertEqual(d["profiles"], {"loose": [1.0, 1.5], "tight": [2 / 3, 2 / 3]})
        self.assertEqual(set(d["games"]["2"]), {f"{e:g}" for e in HU_GRID})
        want = set()
        for x in X_GRID:
            want.add(f"{x:g}")
            want |= {f"{x:g},{y:g},{seat}" for y in Y_GRID if y < x for seat in ("BTN", "SB", "BB")}
        self.assertEqual(set(d["games"]["3"]), want)
        self.assertEqual(len(want) + len(HU_GRID), 491)
        for n, nodes in (("2", NODES2), ("3", NODES3)):
            for key, entry in d["games"][n].items():
                for profile in SX.PROFILES:
                    self.assertEqual(set(entry[profile]), nodes, (n, key, profile))
                    for evs in entry[profile].values():
                        self.assertEqual(len(evs), 169)
                # a chip game with no fee: what one player wins the others lose
                self.assertAlmostEqual(sum(entry["value"]), 0.0, delta=0.02, msg=(n, key))

    def test_decisions_the_solution_never_reaches_are_listed(self):
        """With 1bb in the small blind a player calls every all-in, so "the small blind folded" never comes."""
        d = self.d["games"]["3"]
        self.assertIn("2:1", d["4,1,SB"].get("never", []))
        for key, entry in d.items():
            self.assertLessEqual(set(entry.get("never", [])), NODES3 - {"0:0"}, key)

    def test_the_best_hands_always_go_in_and_the_worst_do_not_from_the_button(self):
        for key, entry in self.d["games"]["3"].items():
            evs = entry["solid"]["0:0"]
            for hand in ("AA", "KK", "AKs"):
                self.assertGreater(evs[HAND_INDEX[hand]], 0, (key, hand))
            x = float(key.split(",")[0])
            if x >= 4:
                self.assertLess(evs[HAND_INDEX["72o"]], 0, key)

    def test_a_big_blind_with_nothing_behind_calls_everything(self):
        """A big blind of 1bb is all-in from posting: calling costs nothing."""
        for x in X_GRID:
            evs = self.d["games"]["3"][f"{x:g},1,BB"]["solid"]["2:1"]
            self.assertTrue(all(e >= -0.5 for e in evs), x)                 # zero, give or take the noise (1/100 bb)


@unittest.skipUnless(SX.available(), "poker_coach/data/spin_exact.json is missing")
class Reading(unittest.TestCase):
    def test_of_three_stacks_two_numbers_matter(self):
        self.assertEqual(SX.reduce([20, 8, 8]), (8, 8, -1))
        self.assertEqual(SX.reduce([12, 5, 8]), (8, 5, 1))
        self.assertEqual(SX.reduce([3, 10, 10]), (10, 3, 0))
        self.assertEqual(SX.reduce([6, 6, 6]), (6, 6, -1))
        self.assertEqual(SX.reduce([4, 9, 30]), (9, 4, 0))

    def test_the_biggest_stack_is_cut_down_to_the_second(self):
        for stacks, same in (([30, 6, 4], [6, 6, 4]), ([5, 20, 9], [5, 9, 9]), ([12, 12, 40], [12, 12, 12])):
            for player, mask in ((0, 0), (1, 0), (1, 1), (2, 1), (2, 3)):
                self.assertEqual(SX.node(3, stacks, player, mask), SX.node(3, same, player, mask), (stacks, player, mask))

    def test_on_the_grid_the_answer_is_the_solution(self):
        d = SX._data()
        for key, stacks in (("10", [10, 10, 10]), ("10,3,BB", [10, 10, 3]), ("16,6,BTN", [6, 16, 16]),
                            ("8,2,SB", [8, 2, 8])):
            for nd, evs in d["games"]["3"][key]["solid"].items():
                player, mask = (int(v) for v in nd.split(":"))
                got = SX.node(3, stacks, player, mask)
                self.assertEqual(got, [e / 100 for e in evs], (key, nd))
        self.assertEqual(SX.node(2, [9, 30], 0, 0), [e / 100 for e in d["games"]["2"]["9"]["solid"]["0:0"]])

    def test_between_two_stacks_the_answers_are_drawn_in_a_line(self):
        lo, hi = SX.node(3, [10, 10, 10], 0, 0), SX.node(3, [12, 12, 12], 0, 0)
        mid = SX.node(3, [11, 11, 11], 0, 0)
        for a, b, m in zip(lo, hi, mid):
            self.assertAlmostEqual(m, (a + b) / 2, places=9)
        # along the short stack first, at a solved X
        lo, hi = SX.node(3, [10, 10, 4], 2, 1), SX.node(3, [10, 10, 5], 2, 1)
        mid = SX.node(3, [10, 10, 4.5], 2, 1)
        for a, b, m in zip(lo, hi, mid):
            self.assertAlmostEqual(m, (a + b) / 2, places=9)
        # outside the grid: nothing
        self.assertIsNone(SX.node(3, [40, 40, 40], 0, 0))
        self.assertIsNone(SX.node(2, [0.5, 10], 0, 0))

    def test_a_short_stack_under_one_big_blind_is_read_as_one(self):
        self.assertEqual(SX.node(3, [10, 10, 0.6], 0, 0), SX.node(3, [10, 10, 1], 0, 0))

    def test_the_game_that_was_solved(self):
        for n, stacks in ((3, [10, 7, 4]), (2, [6, 14])):
            self.assertIsNotNone(SX.covered(setup(stacks), 0))
        self.assertIsNotNone(SX.covered(setup([10, 7, 4]), 2, [0, 1]))

    def test_and_the_games_that_were_not(self):
        self.assertIsNone(SX.covered(setup([10, 10, 10], bb_ante=1.0), 0))            # a big blind ante
        self.assertIsNone(SX.covered(setup([10, 10, 10], ante=0.1), 0))               # every player antes
        self.assertIsNone(SX.covered(setup([10, 10, 10], sb=0.4), 0))                 # other blinds
        self.assertIsNone(SX.covered(setup([10, 10, 10, 10]), 0))                     # four players
        self.assertIsNone(SX.covered(setup([40, 40, 40]), 0))                          # deeper than the grid
        self.assertIsNone(SX.covered(setup([10, 10, 10]), 2))                          # the big blind is never first in
        self.assertIsNone(SX.covered(setup([10, 10, 10]), 1, [2]))                     # an all-in behind the actor

    def test_the_players_around_the_actor_choose_the_answers(self):
        self.assertEqual(SX.profile_of(["loose", "unknown", "loose"], 1), "loose")
        self.assertEqual(SX.profile_of(["tight", "tight", "loose"], 2), "tight")
        self.assertEqual(SX.profile_of(["loose", "tight", "loose"], 0), "solid")
        self.assertEqual(SX.profile_of(["tag", "unknown", "unknown"], 0), "solid")
        self.assertEqual(SX.profile_of(None, 0), "solid")

    def test_what_is_called_close_goes_by_the_noise_of_the_number(self):
        self.assertEqual(SX.close(5), SX.CLOSE_BB)
        self.assertAlmostEqual(SX.close(20), 0.1)
        self.assertGreater(SX.close(20, profile="loose"), SX.close(20))

    def test_the_plays_of_an_opponent_who_plays_more_or_fewer_hands(self):
        evs = SX.node(3, [10, 10, 10], 0, 0)
        base = SX.width(evs)
        more = SX.plays(evs, 1.5)
        self.assertAlmostEqual(100 * sum(c for c, w in zip(COMBO_COUNT, more) if w) / 1326, 1.5 * base, delta=1.0)
        # the best hands first
        fewer = SX.plays(evs, 2 / 3)
        best = max(range(169), key=lambda h: evs[h])
        self.assertEqual(fewer[best], 1.0)


@unittest.skipUnless(SX.available(), "poker_coach/data/spin_exact.json is missing")
class Engine(unittest.TestCase):
    """The engine reads the exact solution in a spin: no ante, two or three players."""

    def test_first_in_up_to_ten_big_blinds_is_the_solution(self):
        rng = random.Random(5)
        for _ in range(40):
            x = rng.choice([4, 5, 6, 7, 8, 9, 10])
            y = rng.choice([v for v in Y_GRID if v <= x])
            seat = rng.randrange(3)
            stacks = [x, x, x]
            stacks[seat] = y
            hero = rng.choice((BTN, SB))
            if stacks[hero] <= (0.5 if hero == SB else 0):
                continue
            evs = SX.node(3, stacks, hero, 0)
            hand = rng.randrange(169)
            if abs(evs[hand]) < SX.close(x):
                continue
            adv = spin(stacks, HANDS[hand], hero)
            self.assertEqual(first(adv.action), "ALL-IN" if evs[hand] > 0 else "FOLD", (stacks, hero, HANDS[hand], evs[hand], adv.action))
            self.assertTrue(adv.data.get("exact"), (stacks, hero, HANDS[hand]))

    def test_calling_an_all_in_is_the_solution(self):
        rng = random.Random(6)
        for _ in range(40):
            x = rng.choice([3, 5, 8, 12, 16, 20, 25])
            stacks = [x, x, x]
            stacks[rng.randrange(3)] = rng.choice([v for v in Y_GRID if 1.5 <= v <= x])
            hero, facing, mask = rng.choice(((SB, "BTN allin", 1), (BB, "BTN allin", 1), (BB, "SB allin", 2),
                                             (BB, "BTN allin, SB allin", 3)))
            if hero == SB and mask == 1 and stacks[SB] <= 0.5:
                continue
            evs = SX.node(3, stacks, hero, mask)
            hand = rng.randrange(169)
            if abs(evs[hand]) < 1.5 * SX.close(x):
                continue
            adv = spin(stacks, HANDS[hand], hero, facing)
            self.assertEqual(first(adv.action), "CALL" if evs[hand] > 0 else "FOLD",
                             (stacks, hero, facing, HANDS[hand], evs[hand], adv.action))

    def test_heads_up(self):
        for e, hand, want in ((10, "K2o", "ALL-IN"), (10, "72o", "FOLD"), (5, "Q3o", "ALL-IN")):
            self.assertEqual(first(spin([e, e], hand, 0).action), want, (e, hand))
        evs = SX.node(2, [10, 10], 1, 1)
        for hand in ("A2o", "K9o", "22"):
            self.assertEqual(first(spin([10, 10], hand, 1, "SB allin").action), "CALL" if evs[HAND_INDEX[hand]] > 0 else "FOLD")

    def test_heads_up_the_small_blind_opens_most_hands(self):
        """Heads-up the button raises about four hands in five: the big blind defends against that range."""
        self.assertAlmostEqual(100 * sum(c for c, w in zip(COMBO_COUNT, R.villain_open_range(1, heads_up=True)) if w >= 0.5) / 1326, 80, delta=2)
        self.assertEqual(first(spin([25, 25], "Q5o", 1, "SB raise 2bb").action), "CALL")
        self.assertEqual(first(spin([25, 25], "72o", 1, "SB raise 2bb").action), "FOLD")

    def test_a_re_raise_short_handed_is_taken_from_a_wide_range(self):
        """Three-handed and heads-up a re-raise of a raise is far wider than at a full table: 12.5% and 16% of
        hands for a player with no read (a spin guide puts the big blind's at 10 to 15%), a step less for a
        tight one.  A full table keeps its ranges."""
        from poker_coach.cards import range_pct
        self.assertAlmostEqual(range_pct(R.threebet_range(2, "unknown")), 6.7, delta=0.1)
        self.assertAlmostEqual(range_pct(R.threebet_range(2, "unknown", 3)), 12.5, delta=0.1)
        self.assertAlmostEqual(range_pct(R.threebet_range(1, "unknown", 2)), 15.8, delta=0.1)
        self.assertLess(range_pct(R.threebet_range(2, "tight", 3)), range_pct(R.threebet_range(2, "unknown", 3)))
        self.assertGreater(range_pct(R.threebet_range(2, "lag", 3)), range_pct(R.threebet_range(2, "unknown", 3)))
        # the button's raise re-raised small with 20bb: a pair of fives goes on, a hand like K9o does not
        self.assertEqual(first(spin([20, 20, 20], "55", BTN, "hero raise 2bb, SB raise 6bb").action), "ALL-IN")
        self.assertEqual(first(spin([20, 20, 20], "K9o", BTN, "hero raise 2bb, SB raise 6bb").action), "FOLD")

    def test_loose_callers_take_the_weak_steals_away(self):
        for x in (6, 10, 16):
            solid, loose = SX.node(3, [x, x, x], 0, 0, "solid"), SX.node(3, [x, x, x], 0, 0, "loose")
            self.assertLessEqual(SX.width(loose), SX.width(solid) + 1.0, x)
        # and the engine plays them when every opponent is tagged loose
        evs_loose = SX.node(3, [10, 10, 10], 0, 0, "loose")
        hand = next(h for h in range(169) if SX.node(3, [10, 10, 10], 0, 0)[h] > 0.1 and evs_loose[h] < -0.1)
        self.assertEqual(first(spin([10, 10, 10], HANDS[hand], BTN).action), "ALL-IN")
        self.assertEqual(first(spin([10, 10, 10], HANDS[hand], BTN, opp="loose").action), "FOLD")

    def test_the_chip_leader_who_is_short_plays_the_short_game(self):
        """A table leader with 8bb against 6bb and 5bb: the two extra big blinds can never be won or lost, so
        the answer is the one for 6/6/5bb, which is far wider than a deep stack's."""
        for hand in ("K7o", "Q9s", "A2o", "T8o", "55"):
            self.assertEqual(spin([8, 6, 5], hand, BTN).action, spin([6, 6, 5], hand, BTN).action, hand)

    def test_tournaments_are_not_touched(self):
        """With an ante the game is not a spin: the tournament's tables answer as before."""
        h, cards = parse_hand("K9o")
        spot = P.quick_spot(h, cards, 10, 3, "BTN", "")
        self.assertIsNone(SX.covered(spot.setup, 0))


if __name__ == "__main__":
    unittest.main()
