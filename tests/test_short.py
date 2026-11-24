"""All-ins of 2 to 20 big blinds: the exact solution (poker_coach/short.py), and the engine reading it.

The data file is made by tools/build_short.py with the solver in tools/aof_solver.c.  Nothing here runs
the solver: the tests hold the stored answers to what any such solution must look like, and hold the
engine to them where the game is theirs.

Two games are in the file, one for each kind of ante: the big blind pays one big blind for the table
("bb"), or every player pays an eighth of a big blind ("player").  The classes up to ``Engine`` are about
the first unless they say otherwise; ``EveryPlayerAntes`` is the second, and what the ante changes.
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
from poker_coach import short as S                             # noqa: E402
from poker_coach.cards import COMBO_COUNT, HAND_INDEX, HANDS, parse_hand   # noqa: E402
from poker_coach.icm import Prizes, default_payouts            # noqa: E402
from poker_coach.pushfold import HandSetup                     # noqa: E402

SEATS = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB")
GRID = (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 16.0, 20.0)     # every stack of the push-or-fold zone, and three deeper
PUSH_OR_FOLD = 10.0             # up to here every hand is an all-in or a fold, and the whole answer is the exact game's
TABLES = {"bb": (3, 4, 5, 6, 9),                # with a big blind ante 7 and 8 players are the last seats of the nine
          "player": (3, 4, 5, 6, 7, 8, 9)}      # with an ante from every player the pot goes with the table: each is solved
ANTES = {"bb": (0.0, 1.0), "player": (0.125, 0.0)}     # what every player pays, and what the big blind pays for the table


def setup(stack, players=9, **kw):
    return HandSetup([float(stack)] * players, 0.5, 1.0, kw.get("ante", 0.0), kw.get("bb_ante", 1.0))


def each(stack, players=9, ante=S.PLAYER_ANTE):
    """Every player antes an eighth of a big blind and the big blind no more: the second solved game."""
    return HandSetup([float(stack)] * players, 0.5, 1.0, ante, 0.0)


def go(hand, stack, pos, facing="", players=9, opp=None, ante="bb"):
    h, cards = parse_hand(hand)
    spot = P.quick_spot(h, cards, stack, players, pos, facing, ante=ante)
    if opp:
        spot.types = [opp] * players
    return P.advise(spot)


def width(evs):
    return S.width(evs)


class Data(unittest.TestCase):
    def test_the_file_is_there_and_whole(self):
        self.assertTrue(S.available(), "poker_coach/data/short.json is missing or out of date: python3 tools/build_short.py")
        with open(os.path.join(ROOT, "poker_coach", "data", "short.json")) as fh:
            d = json.load(fh)
        self.assertEqual((d["version"], d["sb"], d["bb"]), (S.DATA_VERSION, 0.5, 1))
        self.assertEqual(list(d["antes"]), list(S.KINDS))           # the two games, side by side
        self.assertEqual(S.kinds(), ("bb", "player"))
        self.assertTrue(S.available("bb") and S.available("player"))
        for kind, part in d["antes"].items():
            self.assertEqual((part["ante"], part["bb_ante"]), ANTES[kind], kind)
            # two passes: every hand 10,000 times, and the hands that left near zero ten times that
            self.assertEqual((part["train"], part["samples"]), (40_000_000, 10_000), kind)
            self.assertEqual(part["fine"], {"samples": 100_000, "all_ins": 1, "band": [0.05, 0.04]}, kind)
            self.assertEqual(S.games(kind), TABLES[kind])
            self.assertEqual(S.top(kind), GRID[-1])
            for players in S.games(kind):
                self.assertEqual(S.stacks(players, kind), GRID, (kind, players))
                game = part["games"][str(players)]
                for stack in S.stacks(players, kind):
                    nodes = game["nodes"][f"{stack:g}"]
                    # every player with nobody, one player or two players all-in before him; the big blind is never first in
                    self.assertEqual(len(nodes), sum(1 + i + i * (i - 1) // 2 for i in range(players)) - 1, (kind, players, stack))
                    for key, evs in nodes.items():
                        self.assertEqual(len(evs), 169, (kind, players, stack, key))
                    # what the seats win and lose in a hand adds up to nothing
                    value = game["value"][f"{stack:g}"]
                    self.assertAlmostEqual(sum(value), 0.0, delta=0.02)
                    # nobody does worse than by folding every hand, which costs a seat before the blinds its ante
                    # and no more; the two blinds pay for the table
                    for won in value[:-2]:
                        self.assertGreater(won, -ANTES[kind][0] - 0.01, (kind, players, stack, value))
                    self.assertLess(value[-1] + value[-2], -0.05, (kind, players, stack, value))
                    if kind == "bb":                # ... the big blind most of all when the whole ante is his
                        self.assertLess(value[-1], -0.4, (kind, players, stack))
                    # the second pass took a part of the hands, not none and not most
                    with_one = sum(1 for key in nodes if bin(int(key.split(":")[1])).count("1") <= 1)
                    self.assertTrue(0.03 * 169 * with_one < game["again"][f"{stack:g}"] < 0.5 * 169 * with_one, (kind, players, stack))
        self.assertEqual(S.table_for(6), 6)
        self.assertEqual(S.table_for(8), 9)             # seven and eight players: the last seats of the nine
        self.assertEqual(S.table_for(7), 9)
        self.assertEqual(S.table_for(8, "player"), 8)   # ... which is no way to read an ante from every player:
        self.assertEqual(S.table_for(7, "player"), 7)   # the nine has an eighth of a big blind more in the pot
        self.assertIsNone(S.table_for(2, "player"))     # two players: the engine's own solver is exact

    def test_between_two_stacks_the_answers_are_drawn_in_a_line(self):
        for a, b in ((2.0, 3.0), (12.0, 16.0)):
            lo, hi, mid = S.node(a, 6, 0), S.node(b, 6, 0), S.node((a + b) / 2, 6, 0)
            for x, y, z in zip(lo, hi, mid):
                self.assertAlmostEqual(z, (x + y) / 2, places=9)
        quarter = S.node(13.0, 8, 1 << 6)
        for x, y, z in zip(S.node(12.0, 8, 1 << 6), S.node(16.0, 8, 1 << 6), quarter):
            self.assertAlmostEqual(z, x + (y - x) / 4, places=9)
        self.assertIsNone(S.node(S.top() + 0.5, 6, 0))
        self.assertIsNone(S.node(1.5, 6, 0))
        self.assertIsNone(S.node(3.0, 8, 0b111))                       # three all-in: not kept
        self.assertIsNone(S.node(3.0, 8, 0))                           # the big blind first in: no such decision
        self.assertIsNone(S.node(3.0, 5, 0, 7))                        # no table of seven was solved with a big blind ante
        self.assertIsNotNone(S.node(3.0, 5, 0, 7, "player"))           # ... and one was with the ante of every player
        for a, b in ((2.0, 3.0), (12.0, 16.0)):
            lo, hi, mid = (S.node(x, 4, 0, 6, "player") for x in (a, b, (a + b) / 2))
            for x, y, z in zip(lo, hi, mid):
                self.assertAlmostEqual(z, (x + y) / 2, places=9)


class Shape(unittest.TestCase):
    """What an exact solution must look like, whoever made it."""

    def test_the_best_hands_always_go_in_and_the_worst_do_not_from_the_first_seat(self):
        for stack in S.stacks():
            for player in range(8):
                evs = S.node(stack, player, 0)
                for hand in ("AA", "KK", "QQ", "AKs", "AKo"):
                    self.assertGreater(evs[HAND_INDEX[hand]], 0.3, (stack, player, hand))
            if stack >= 3:
                for hand in ("72o", "32o", "83o"):
                    self.assertLess(S.node(stack, 0, 0)[HAND_INDEX[hand]], -0.2, (stack, hand))

    def test_a_later_seat_moves_all_in_with_more_hands(self):
        for stack in S.stacks():
            widths = [width(S.node(stack, player, 0)) for player in range(8)]
            for early, late in zip(widths, widths[1:]):
                self.assertLess(early, late + 2.5, (stack, widths))     # two and a half points of noise
            self.assertLess(widths[0] + 12, widths[6], (stack, widths))   # the button far more than the first seat
            self.assertLess(widths[6] + 15, widths[7], (stack, widths))   # and the small blind far more than the button

    def test_a_hand_that_goes_in_from_a_seat_goes_in_from_the_next(self):
        """Nearly so: what the second pass is for.  After the first pass alone three to eleven hands a stack
        were in from one seat and out from the next; a chart with that in it reads as a mistake.  After the
        second none is left up to 7bb and one to three up to 12bb, each a hand worth nothing either way.
        (With 16 and 20bb the first seats' numbers for the small suited aces lie within a few hundredths of
        each other and of zero, and more hands cross; at that depth no table moves all-in on such a number.)"""
        for stack in S.stacks():
            odd = []
            for player in range(6):                     # up to the cutoff and the button; the small blind is another game
                here, behind = S.node(stack, player, 0), S.node(stack, player + 1, 0)
                odd += [(SEATS[player], HANDS[h], here[h], behind[h]) for h in range(169) if here[h] > 0 >= behind[h]]
            self.assertLessEqual(len(odd), 0 if stack <= 7 else 4 if stack <= 12 else 12, (stack, odd))
            for _, _, mine, next_one in odd:            # the two numbers are within their noise of each other
                self.assertLess(mine - next_one, 4 * S.close(stack), (stack, odd))

    def test_with_three_big_blinds_the_first_seat_plays_a_quarter_of_its_hands_not_most_of_them(self):
        """The number this file exists for: one caller at a time said 84%."""
        self.assertTrue(20 < width(S.node(3.0, 0, 0)) < 32, width(S.node(3.0, 0, 0)))
        self.assertTrue(40 < width(S.node(3.0, 6, 0)) < 60, width(S.node(3.0, 6, 0)))
        self.assertGreater(width(S.node(3.0, 7, 0)), 90)

    def test_a_shorter_stack_moves_all_in_with_at_least_as_many_hands(self):
        grid = S.stacks()
        for player in range(8):
            widths = [width(S.node(stack, player, 0)) for stack in grid]
            for i in range(len(grid) - 1):
                if grid[i] >= 3:                                         # with 2bb the big blind is all-in blind: a game of its own
                    self.assertGreater(widths[i] + 4.0, widths[i + 1], (SEATS[player], widths))

    def test_calling_an_all_in(self):
        for stack in S.stacks():
            # the big blind has a price nobody else has
            for shover in (0, 3, 6):
                self.assertGreater(width(S.node(stack, 8, 1 << shover)), width(S.node(stack, 7, 1 << shover)) - 1, (stack, shover))
                self.assertGreater(width(S.node(stack, 7, 1 << shover)), width(S.node(stack, 6, 1 << shover)) - 1) if shover < 6 else None
            # an all-in from a later seat is a wider range: it is called with more hands
            self.assertGreater(width(S.node(stack, 8, 1 << 7)) + 1, width(S.node(stack, 8, 1 << 0)), stack)
            self.assertGreater(width(S.node(stack, 6, 1 << 5)) + 2, width(S.node(stack, 6, 1 << 0)), stack)
            # the player next to the first seat has seven players behind him: he needs a real hand
            self.assertLess(width(S.node(stack, 1, 1 << 0)), width(S.node(stack, 0, 0)), stack)
            # aces call anything; a second all-in in front makes every other call rarer for a player with others behind
            self.assertGreater(S.node(stack, 6, (1 << 0) | (1 << 3))[HAND_INDEX["AA"]], 1.0)
            self.assertLess(width(S.node(stack, 6, (1 << 0) | (1 << 3))), width(S.node(stack, 6, 1 << 3)) + 1, stack)
        # with two big blinds and an ante of one the big blind is all-in before the cards: he "calls" with all of them
        self.assertEqual(width(S.node(2.0, 8, 1 << 0)), 100.0)

    def test_what_folded_is_out_of_the_deck(self):
        """The same seats at a smaller table: fewer players have folded their middle cards, and the big blind
        calls an all-in with more hands.  (Read from the nine, a table of six would call ten points too tight.)"""
        for stack in (4.0, 5.0, 6.0, 8.0):
            six = width(S.node(stack, 5, 1 << 3, 6))            # big blind against the button, six players
            nine = width(S.node(stack, 8, 1 << 6, 9))           # the same two seats of nine
            three = width(S.node(stack, 2, 1 << 0, 3))          # and of three, where nobody folded before the button
            self.assertGreater(six, nine + 3, stack)
            self.assertGreater(three, six - 1, stack)
        # first in the difference is a few hands
        for stack in (3.0, 5.0, 8.0):
            self.assertAlmostEqual(width(S.node(stack, 3, 0, 6)), width(S.node(stack, 6, 0, 9)), delta=6, msg=str(stack))


class Covered(unittest.TestCase):
    def test_the_game_that_was_solved(self):
        self.assertEqual(S.covered(setup(3), 0), 3.0)
        self.assertEqual(S.covered(setup(3), 6, [0]), 3.0)
        self.assertEqual(S.covered(setup(3), 8, [0, 5]), 3.0)
        self.assertEqual(S.covered(setup(S.top()), 4), S.top())
        self.assertEqual(S.covered(setup(4, players=6), 0), 4.0)        # six players: the last six seats of nine
        self.assertEqual(S.seat(6, 0), 3)

    def test_the_ante_says_which_game(self):
        self.assertEqual(S.ante_kind(setup(3)), "bb")
        self.assertEqual(S.ante_kind(each(3)), "player")
        self.assertEqual(S.covered(each(3), 0), 3.0)
        self.assertEqual(S.covered(each(3, players=8), 5, [0]), 3.0)
        self.assertEqual(S.covered(each(3, players=7), 6, [0, 4]), 3.0)
        self.assertEqual(S.answer(each(3), 0), S.node(3.0, 0, 0, 9, "player"))
        self.assertEqual(S.answer(each(3, players=8), 7, [2]), S.node(3.0, 7, 1 << 2, 8, "player"))     # a table of eight: its own
        self.assertEqual(S.answer(setup(3, players=8), 7, [2]), S.node(3.0, 8, 1 << 3, 9, "bb"))        # ... and the nine's last seats
        self.assertNotEqual(S.answer(each(3), 0), S.answer(setup(3), 0))
        # chips, not big blinds: 300 and 600 with 75 from every player, as a table is tracked
        chips = HandSetup([3600.0] * 8, 300.0, 600.0, 75.0, 0.0)
        self.assertEqual(S.covered(chips, 2), 6.0)
        self.assertEqual(S.answer(chips, 2), S.node(6.0, 2, 0, 8, "player"))
        # the levels of a structure are not all an eighth: 30 at 125/250 is 0.12, 40 at 150/300 is 0.133.  Those
        # are read from the solution for an eighth, and the engine says so; a tenth or a sixth is another game
        for ante, bb in ((30, 250), (40, 300), (45, 350), (65, 500)):
            level = HandSetup([10.0 * bb] * 8, bb / 2, bb, ante, 0.0)
            self.assertEqual(S.ante_kind(level), "player", (ante, bb))
            self.assertFalse(S.same_ante(level), (ante, bb))
            self.assertEqual(S.covered(level, 0), 10.0, (ante, bb))
        self.assertTrue(S.same_ante(each(3)) and S.same_ante(setup(3)) and S.same_ante(chips))
        for ante in (0.1, 0.15, 0.25, 0.05):
            self.assertIsNone(S.ante_kind(each(3, ante=ante)), ante)
            self.assertIsNone(S.covered(each(3, ante=ante), 0), ante)
            self.assertFalse(S.same_ante(each(3, ante=ante)), ante)
        self.assertIsNone(S.ante_kind(setup(3, ante=0.125, bb_ante=1.0)))       # both antes at once
        self.assertIsNone(S.ante_kind(setup(3, bb_ante=0.5)))                   # half a big blind ante
        self.assertIsNone(S.ante_kind(HandSetup([3.0] * 9, 0.4, 1.0, 0.125, 0.0)))     # another small blind
        short_ante = HandSetup([3.0] * 7 + [0.1, 3.0], 0.5, 1.0, 0.125, 0.0)    # a player who cannot pay his ante
        self.assertIsNone(S.ante_kind(short_ante))

    def test_and_the_games_that_were_not(self):
        self.assertIsNone(S.covered(setup(S.top() + 1), 0))             # deeper: the engine's own solver
        self.assertIsNone(S.covered(setup(1.5), 0))
        self.assertIsNone(S.covered(setup(3, players=2), 0))            # heads-up: the engine is exact there
        self.assertIsNone(S.covered(each(3, players=2), 0))
        self.assertIsNone(S.covered(each(S.top() + 1), 0))
        self.assertIsNone(S.covered(setup(3, ante=0.25, bb_ante=0.0), 0))       # every player antes a quarter: another game
        self.assertIsNone(S.covered(setup(3, bb_ante=0.0), 0))          # no ante
        self.assertIsNone(S.covered(setup(3), 8, [0, 3, 5]))            # three all-in
        self.assertIsNone(S.covered(setup(3), 3, [5]))                  # an all-in from a seat behind is not "before"
        short_behind = HandSetup([3.0] * 7 + [2.0, 3.0], 0.5, 1.0, 0.0, 1.0)
        self.assertIsNone(S.covered(short_behind, 0))                   # a shorter stack still to act
        self.assertEqual(S.covered(short_behind, 8, [0]), 3.0)          # ... but not when he has folded
        deep_behind = HandSetup([3.0] * 6 + [20.0, 9.0, 40.0], 0.5, 1.0, 0.0, 1.0)
        self.assertEqual(S.covered(deep_behind, 0), 3.0)                # deeper stacks behind can lose no more than the 3bb
        two_sizes = HandSetup([3.0, 4.0] + [5.0] * 7, 0.5, 1.0, 0.0, 1.0)
        self.assertIsNone(S.covered(two_sizes, 8, [0, 1]))              # two all-ins of different sizes

    def test_prizes_reads_and_empty_seats_are_left_to_the_solver(self):
        chips = Prizes()
        self.assertIsNotNone(P._exact_open(setup(3), 0, chips))
        self.assertIsNotNone(P._exact_open(each(3), 0, chips))
        self.assertIsNone(P._exact_open(each(3), 0, Prizes(default_payouts(200, 30), 31, 3.0)))
        prizes = Prizes(default_payouts(200, 30), 31, 3.0)
        self.assertIsNone(P._exact_open(setup(3), 0, prizes))
        self.assertIsNone(P._exact_open(setup(3), 0, chips, caller_prizes=prizes))
        self.assertIsNone(P._exact_open(setup(3), 0, chips, away=[False] * 8 + [True]))
        self.assertIsNone(P._exact_open(setup(3), 0, chips, types=["unknown"] * 8 + ["maniac"]))
        self.assertIsNotNone(P._exact_open(setup(3), 0, chips, types=["loose"] * 9))


class Engine(unittest.TestCase):
    """Where the game is the solved one, the engine's answer is the stored one, hand for hand."""

    def setUp(self):
        self.before = R.set_style("win")

    def tearDown(self):
        R.set_style(self.before)

    def test_first_in(self):
        rng = random.Random(11)
        for _ in range(60):
            stack = rng.choice(S.stacks())
            players = rng.choice((9, 9, 8, 6, 4, 3))
            index = rng.randrange(players - 1)
            hand = rng.randrange(169)
            pos = R.position_name(players - 1 - index, players)
            adv = go(HANDS[hand], stack, pos, players=players)
            base = S.table_for(players)                  # six, four and three players: their own solution
            ev = S.node(stack, index + base - players, 0, base)[hand]
            self.assertAlmostEqual(adv.data["shove_ev_bb"], ev, places=6)
            if stack <= PUSH_OR_FOLD:
                self.assertEqual(adv.action == "ALL-IN", ev > 0, (HANDS[hand], stack, pos, players, adv.action, ev))
                self.assertTrue(adv.data.get("exact"))
            else:
                # deeper there are small raises as well: the all-in's number is the exact one, the play is the engine's
                self.assertNotIn("exact", adv.data)
                if adv.action == "ALL-IN":
                    self.assertGreater(ev, 0, (HANDS[hand], stack, pos, players))

    def test_the_hands_it_used_to_get_wrong(self):
        self.assertEqual(go("72o", 3, "UTG").action, "FOLD")
        self.assertEqual(go("T7s", 3, "UTG").action, "FOLD")
        self.assertEqual(go("K4o", 3, "UTG").action, "FOLD")
        self.assertEqual(go("A8o", 3, "UTG").action, "ALL-IN")
        self.assertEqual(go("A2o", 3, "BTN", "UTG allin").action, "FOLD")
        self.assertEqual(go("KQo", 3, "BTN", "UTG allin").action, "CALL")
        self.assertEqual(go("72o", 3, "BB", "UTG allin").action, "CALL")       # one more big blind into a pot of seven

    def test_calling_one_all_in_and_two(self):
        rng = random.Random(12)
        for _ in range(40):
            stack = rng.choice(S.stacks())
            hero = rng.randrange(1, 9)
            first = rng.randrange(hero)
            two = hero >= 2 and rng.random() < 0.4
            second = rng.choice([j for j in range(hero) if j != first]) if two else None
            in_front = sorted([first] + ([second] if two else []))
            hand = rng.randrange(169)
            facing = ", ".join(f"{SEATS[j]} allin" for j in in_front)
            adv = go(HANDS[hand], stack, SEATS[hero], facing)
            mask = sum(1 << j for j in in_front)
            ev = S.node(stack, hero, mask)[hand]
            mine = adv.data["exact_ev"]
            if stack <= PUSH_OR_FOLD:
                self.assertAlmostEqual(mine, ev, places=6)
            else:
                # above ten big blinds a player with no read moves in with a little less than the solved game's
                # range (a tenth less at 20bb, as the deeper tables take him): the exact answer, moved by that
                self.assertLess(abs(mine - ev), 1.5, (HANDS[hand], stack, SEATS[hero], facing))
                self.assertLess(mine, ev + 0.1, (HANDS[hand], stack, SEATS[hero], facing))
            self.assertEqual(adv.action.startswith(("CALL", "ALL-IN")), mine > 0, (HANDS[hand], stack, SEATS[hero], facing, adv.action, mine))
            if not two:
                # said in the engine's own words: the equity and what is needed stand on the same side as the answer
                self.assertEqual(adv.data["equity"] >= adv.data["need"], mine >= 0, (HANDS[hand], facing))

    def test_a_raise_this_short_commits_the_raiser_and_is_answered_as_his_all_in(self):
        for hand in ("KTo", "K4o", "A2s", "98s", "J7o"):
            raised, moved = go(hand, 3, "BTN", "CO raise 2bb"), go(hand, 3, "BTN", "CO allin")
            self.assertEqual(raised.action.startswith(("CALL", "ALL-IN")), moved.action.startswith("CALL"), hand)
            self.assertIn("committed", raised.situation)

    def test_what_the_opponents_setting_moves(self):
        """First in, nothing: the exact game is its own.  Calling an all-in, the hands the all-in player is taken
        to hold: fewer for a tight player, more for a loose one, as in every other table."""
        for hand, pos in (("K9o", "CO"), ("A5o", "UTG+1"), ("T8s", "BTN")):
            answers = {go(hand, 4, pos, opp=opp).action for opp in ("unknown", "tight", "loose")}
            self.assertEqual(len(answers), 1, (hand, pos, answers))
        calls = {}
        for opp in ("tight", "unknown", "loose"):
            calls[opp] = sum(1 for h in range(169) if go(HANDS[h], 5, "BTN", "CO allin", opp=opp).action.startswith("CALL"))
        self.assertLess(calls["tight"], calls["unknown"])
        self.assertLess(calls["unknown"], calls["loose"])
        # with no read the answer is the exact game's own
        for h in random.Random(5).sample(range(169), 30):
            adv = go(HANDS[h], 5, "BTN", "CO allin")
            self.assertEqual(adv.action.startswith("CALL"), S.node(5.0, 6, 1 << 5)[h] > 0, HANDS[h])

    def test_how_wide_an_all_in_is_taken_to_be(self):
        """The solved game's own range up to 10bb; from there down to the engine's usual tenth less at 20bb, so
        the tables on both sides of 20bb say the same of a player with no read."""
        self.assertEqual(P._exact_width("unknown", 5), 1.0)
        self.assertEqual(P._exact_width("unknown", 10), 1.0)
        self.assertAlmostEqual(P._exact_width("unknown", 15), 0.95)
        self.assertAlmostEqual(P._exact_width("unknown", 20), R.PLAYER_TYPES["unknown"]["shove_mult"])
        self.assertAlmostEqual(P._exact_width("unknown", 40), R.PLAYER_TYPES["unknown"]["shove_mult"])
        for kind in ("tight", "loose"):
            self.assertAlmostEqual(P._exact_width(kind, 20), R.PLAYER_TYPES[kind]["shove_mult"])
            self.assertAlmostEqual(P._exact_width(kind, 5), R.PLAYER_TYPES[kind]["shove_mult"] / R.PLAYER_TYPES["unknown"]["shove_mult"])
        self.assertEqual(P._exact_width("tag", 16), 1.0)
        # with 16bb the big blind calls a button all-in with no more hands than the solved game's, and nearly as many
        mine = sum(c for h, c in enumerate(COMBO_COUNT) if go(HANDS[h], 16, "BB", "BTN allin").action.startswith("CALL"))
        own = sum(c for c, e in zip(COMBO_COUNT, S.node(16.0, 8, 1 << 6)) if e > 0)
        self.assertLessEqual(mine, own)
        self.assertGreater(mine, 0.8 * own)

    def test_what_is_called_close_goes_by_the_noise_of_the_number(self):
        """About twice the noise: it grows with the stack, and with two players all-in the first pass stands."""
        self.assertEqual((S.close(5), S.close(10), S.close(20)), (0.05, 0.05, 0.1))
        self.assertEqual((S.close(5, 2), S.close(20, 2)), (0.15, 0.3))
        self.assertEqual(P._exact_conf(0.04, 8, 1), "close")
        self.assertEqual(P._exact_conf(0.12, 8, 1), "standard")
        self.assertEqual(P._exact_conf(0.12, 8, 2), "close")
        self.assertEqual(P._exact_conf(0.4, 20, 2), "standard")        # clear starts at twice the band
        self.assertEqual(P._exact_conf(0.7, 20, 2), "clear")
        # the engine says so: a call within the band is close, whichever side it falls on
        evs = S.node(8.0, 8, 1 << 6)
        edge = min(range(169), key=lambda h: abs(evs[h]) if evs[h] != 0 else 9)
        self.assertLess(abs(evs[edge]), 0.05)
        self.assertEqual(go(HANDS[edge], 8, "BB", "BTN allin").confidence, "close")
        sure = max(range(169), key=lambda h: evs[h])
        self.assertEqual(go(HANDS[sure], 8, "BB", "BTN allin").confidence, "clear")

    def test_one_stack_deeper_the_engine_answers_by_itself(self):
        adv = go("A8o", S.top() + 1, "SB")              # the small blind's all-in is weighed up to 25bb
        self.assertNotIn("exact", adv.data)
        self.assertIn("shove_ev_bb", adv.data)
        self.assertIn("when called you have", " ".join(adv.numbers))
        self.assertNotIn("exact", go("A8o", S.top() + 2, "BB", "CO allin").data)

    def test_above_ten_big_blinds_the_all_in_is_one_play_among_others(self):
        """The number of the all-in is the exact one; whether to move in, raise small or fold is the engine's."""
        adv = go("AA", 16, "UTG")
        self.assertTrue(adv.action.startswith("RAISE"), adv.action)
        self.assertAlmostEqual(adv.data["shove_ev_bb"], S.node(16.0, 0, 0)[HAND_INDEX["AA"]], places=6)
        self.assertNotIn("exact", adv.data)
        self.assertIn("solved exactly", " ".join(adv.numbers))
        # between two solved stacks: the line between them
        mid = go("A9s", 14, "CO").data["shove_ev_bb"]
        self.assertAlmostEqual(mid, (S.node(12.0, 5, 0)[HAND_INDEX["A9s"]] + S.node(16.0, 5, 0)[HAND_INDEX["A9s"]]) / 2, places=6)
        # a call of an all-in is the same decision at every depth: the exact answer, and it says so
        called = go("AQo", 16, "BTN", "CO allin")
        self.assertTrue(called.data.get("exact"))
        self.assertEqual(called.action.startswith("CALL"), called.data["exact_ev"] > 0)
        self.assertLess(abs(called.data["exact_ev"] - S.node(16.0, 6, 1 << 5)[HAND_INDEX["AQo"]]), 1.0)

    def test_behind_a_player_who_only_called(self):
        """With six big blinds or less he is not folding: his all-in, with a caller's hands credited; the big blind
        weighs the free flop.  Deeper, the solver's own reading of a caller."""
        self.assertEqual(go("72o", 4, "UTG+1", "UTG limp").action, "FOLD")
        self.assertEqual(go("K4o", 4, "UTG+1", "UTG limp").action, "FOLD")
        self.assertEqual(go("AJo", 4, "UTG+1", "UTG limp").action, "ALL-IN")
        self.assertTrue(go("AJo", 4, "UTG+1", "UTG limp").data.get("exact"))
        self.assertEqual(go("72o", 5, "BB", "BTN limp").action, "CHECK")
        self.assertEqual(go("AJo", 5, "BB", "BTN limp").action, "ALL-IN")
        self.assertNotIn("exact", go("AJo", 8, "UTG+1", "UTG limp").data)
        # no seat behind a caller moves in with most of its hands any more (it was 84% with 4bb)
        played = sum(1 for h in range(169) if go(HANDS[h], 4, "UTG+1", "UTG limp").action == "ALL-IN")
        self.assertLess(played, 45)

    def test_other_games_are_not_touched(self):
        """Prizes in play, or another ante: the solver's answer, as before."""
        h, cards = parse_hand("A8o")
        spot = P.quick_spot(h, cards, 3, 9, "UTG", "")
        spot.prizes = Prizes(default_payouts(200, 30), 31, 3.0)
        self.assertNotIn("exact", P.advise(spot).data)


class EveryPlayerAntes(unittest.TestCase):
    """The second game: an eighth of a big blind from every player, as on GGPoker.  Every table from three to
    nine players is solved as such, because the money in the pot goes with the number of players."""

    K = "player"

    def test_what_every_table_looks_like(self):
        for n in S.games(self.K):
            for stack in S.stacks(n, self.K):
                first_in = [S.node(stack, i, 0, n, self.K) for i in range(n - 1)]
                widths = [width(evs) for evs in first_in]
                for evs in first_in:                        # the best hands always go in
                    for hand in ("AA", "KK", "QQ", "AKs", "AKo"):
                        self.assertGreater(evs[HAND_INDEX[hand]], 0.3, (n, stack, hand))
                for early, late in zip(widths, widths[1:]):     # a later seat with more hands (two and a half points of noise)
                    self.assertLess(early, late + 2.5, (n, stack, widths))
                self.assertLess(widths[-2] + 12 if n > 3 else 0, widths[-1], (n, stack, widths))    # the small blind far more than the button
                big_blind = n - 1
                for shover in range(n - 1):
                    called = width(S.node(stack, big_blind, 1 << shover, n, self.K))
                    if shover < n - 2:                      # the big blind has a price nobody else has
                        self.assertGreater(called, width(S.node(stack, n - 2, 1 << shover, n, self.K)) - 1, (n, stack, shover))
                    self.assertGreater(S.node(stack, big_blind, 1 << shover, n, self.K)[HAND_INDEX["AA"]], 1.0)
                # an all-in from the small blind is the widest range, and is called with the most hands
                self.assertGreater(width(S.node(stack, big_blind, 1 << (n - 2), n, self.K)) + 1,
                                   width(S.node(stack, big_blind, 1 << 0, n, self.K)), (n, stack))
            if n >= 6:
                for stack in S.stacks(n, self.K):
                    if stack >= 3:                          # 7-2 and its like are folds from the first seat
                        for hand in ("72o", "32o", "83o"):
                            self.assertLess(S.node(stack, 0, 0, n, self.K)[HAND_INDEX[hand]], -0.2, (n, stack, hand))

    def test_a_shorter_stack_moves_all_in_with_at_least_as_many_hands(self):
        """From two big blinds up: here the big blind is not all-in from posting with two, as he is when the whole
        ante is his."""
        for n in S.games(self.K):
            grid = S.stacks(n, self.K)
            for player in range(n - 1):
                widths = [width(S.node(stack, player, 0, n, self.K)) for stack in grid]
                for i in range(len(grid) - 1):
                    self.assertGreater(widths[i] + 4.0, widths[i + 1], (n, player, widths))

    def test_a_hand_that_goes_in_from_a_seat_goes_in_from_the_next(self):
        """What the second pass is for, as with the big blind ante: nearly none is left, each worth nothing either way."""
        for n in (9, 8, 7, 6):
            for stack in S.stacks(n, self.K):
                odd = []
                for player in range(n - 3):                 # up to the cutoff and the button; the small blind is another game
                    here, behind = S.node(stack, player, 0, n, self.K), S.node(stack, player + 1, 0, n, self.K)
                    odd += [(player, HANDS[h], here[h], behind[h]) for h in range(169) if here[h] > 0 >= behind[h]]
                self.assertLessEqual(len(odd), 1 if stack <= 7 else 4 if stack <= 12 else 12, (n, stack, odd))
                for _, _, mine, next_one in odd:
                    self.assertLess(mine - next_one, 4 * S.close(stack), (n, stack, odd))

    def test_the_big_blind_has_one_more_big_blind_behind(self):
        """Eight players: the two antes put the same big blind in the pot.  With the big blind ante the big blind
        has paid all of it, and against an all-in of four or five big blinds he has little left to save; with an
        eighth paid he has one big blind more behind, and calls with far fewer hands."""
        for stack, fewer in ((4.0, 12), (5.0, 10), (6.0, 3), (7.0, 2)):
            for shover in (0, 5):                           # against the first seat of eight, and the button
                mine = width(S.node(stack, 7, 1 << shover, 8, self.K))
                theirs = width(S.node(stack, 8, 1 << (shover + 1), 9, "bb"))        # the same seats: the nine's last eight
                self.assertLess(mine + fewer, theirs, (stack, shover, mine, theirs))
        for stack in (8.0, 9.0, 10.0, 12.0, 16.0, 20.0):    # deeper, one big blind is a small part of the stack
            for shover in (0, 5, 6):
                mine = width(S.node(stack, 7, 1 << shover, 8, self.K))
                theirs = width(S.node(stack, 8, 1 << (shover + 1), 9, "bb"))
                self.assertLess(abs(mine - theirs), 6.0, (stack, shover, mine, theirs))
                self.assertLess(mine, theirs + 2.0, (stack, shover, mine, theirs))
        # with two big blinds a big blind ante leaves him all-in from posting.  With his eighth paid he has a
        # decision, and the price makes it for him: seven eighths of a big blind to call into more than four
        self.assertEqual(width(S.node(2.0, 8, 1 << 0, 9, "bb")), 100.0)
        self.assertEqual(width(S.node(2.0, 7, 1 << 0, 8, self.K)), 100.0)
        self.assertGreater(min(S.node(2.0, 7, 1 << 0, 8, self.K)), 0.0)
        # the hands: six players, the big blind against a button all-in of 5bb
        ante_his, ante_all = S.node(5.0, 5, 1 << 3, 6, "bb"), S.node(5.0, 5, 1 << 3, 6, self.K)
        for hand in ("65o", "Q2o", "93s"):
            self.assertGreater(ante_his[HAND_INDEX[hand]], 0.1, hand)
            self.assertLess(ante_all[HAND_INDEX[hand]], -0.1, hand)

    def test_a_smaller_table_plays_for_a_smaller_pot(self):
        """The ante in the pot: 0.375bb at three players, 0.75bb at six, where the big blind ante has a whole big
        blind at every table.  The late seats move all-in first with fewer hands, table for table."""
        for n in (3, 4, 5, 6):
            less = 0.0
            for stack in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
                for player in (n - 3, n - 2):               # the button and the small blind
                    mine, theirs = width(S.node(stack, player, 0, n, self.K)), width(S.node(stack, player, 0, n, "bb"))
                    self.assertLess(mine, theirs + 1.5, (n, stack, player))
                    less += theirs - mine
            self.assertGreater(less, 25 if n == 6 else 30, (n, less))      # over the twelve: two to four points each
        # ... and where the pot is bigger than a big blind ante's, at nine players, with no fewer
        more = sum(width(S.node(stack, player, 0, 9, self.K)) - width(S.node(stack, player, 0, 9, "bb"))
                   for stack in (6.0, 8.0, 10.0) for player in range(7))
        self.assertGreater(more, -8.0, more)

    def test_the_tables_of_eight_and_seven_are_their_own(self):
        """Read from the nine, a table of eight would play for an eighth of a big blind that is not in its pot (and
        a table of seven for a quarter): the first seat of eight has the hands of the nine's second seat less a
        little, not more."""
        for stack in (5.0, 6.0, 8.0, 10.0):
            eight = [width(S.node(stack, i, 0, 8, self.K)) for i in range(7)]
            nine = [width(S.node(stack, i + 1, 0, 9, self.K)) for i in range(7)]
            seven = [width(S.node(stack, i, 0, 7, self.K)) for i in range(6)]
            self.assertLess(sum(eight), sum(nine) + 4, (stack, eight, nine))
            self.assertLess(sum(seven), sum(eight[1:]) + 4, (stack, seven, eight))
            for a, b in zip(eight, nine):
                self.assertAlmostEqual(a, b, delta=7, msg=str((stack, eight, nine)))


class EngineEveryPlayerAntes(unittest.TestCase):
    """With an ante from every player the engine reads the second game, at the table's own size."""

    def setUp(self):
        self.before = R.set_style("win")

    def tearDown(self):
        R.set_style(self.before)

    def test_first_in_is_the_stored_answer_at_every_table_size(self):
        rng = random.Random(21)
        for _ in range(80):
            stack = rng.choice(S.stacks(9, "player"))
            players = rng.choice((9, 8, 8, 7, 6, 5, 4, 3))
            index = rng.randrange(players - 1)
            hand = rng.randrange(169)
            pos = R.position_name(players - 1 - index, players)
            adv = go(HANDS[hand], stack, pos, players=players, ante="player")
            ev = S.node(stack, index, 0, players, "player")[hand]
            self.assertAlmostEqual(adv.data["shove_ev_bb"], ev, places=6)
            self.assertEqual(adv.warnings, [], (HANDS[hand], stack, pos, players))      # no "reads weak hands too well"
            self.assertIn("solved exactly", " ".join(adv.numbers))
            if stack <= PUSH_OR_FOLD:
                self.assertEqual(adv.action == "ALL-IN", ev > 0, (HANDS[hand], stack, pos, players, adv.action, ev))
                self.assertTrue(adv.data.get("exact"))
            elif adv.action == "ALL-IN":
                self.assertGreater(ev, 0, (HANDS[hand], stack, pos, players))

    def test_calling_one_all_in_and_two(self):
        rng = random.Random(22)
        for _ in range(60):
            players = rng.choice((9, 8, 8, 6, 5))
            stack = rng.choice(S.stacks(players, "player"))
            hero = rng.randrange(1, players)
            first = rng.randrange(hero)
            two = hero >= 2 and rng.random() < 0.4
            second = rng.choice([j for j in range(hero) if j != first]) if two else None
            in_front = sorted([first] + ([second] if two else []))
            hand = rng.randrange(169)
            name = lambda j: R.position_name(players - 1 - j, players)      # noqa: E731
            adv = go(HANDS[hand], stack, name(hero), ", ".join(f"{name(j)} allin" for j in in_front), players=players, ante="player")
            ev = S.node(stack, hero, sum(1 << j for j in in_front), players, "player")[hand]
            mine = adv.data["exact_ev"]
            if stack <= PUSH_OR_FOLD:
                self.assertAlmostEqual(mine, ev, places=6)
            else:               # deeper, a player with no read moves in with a little less than the solved range
                self.assertLess(abs(mine - ev), 1.5, (HANDS[hand], stack, players, hero, in_front))
                self.assertLess(mine, ev + 0.1, (HANDS[hand], stack, players, hero, in_front))
            self.assertEqual(adv.action.startswith(("CALL", "ALL-IN")), mine > 0, (HANDS[hand], stack, players, hero, in_front, adv.action))
            self.assertEqual([w for w in adv.warnings if "too well" in w], [])

    def test_the_two_antes_are_two_answers(self):
        """Six players, the big blind against a button all-in of 5bb: 65o calls when the big blind paid the ante
        for the table, and folds when everybody paid an eighth."""
        his = go("65o", 5, "BB", "BTN allin", players=6)
        every = go("65o", 5, "BB", "BTN allin", players=6, ante="player")
        self.assertEqual((his.action, every.action), ("CALL", "FOLD"))
        self.assertTrue(his.data["exact"] and every.data["exact"])
        self.assertAlmostEqual(every.data["exact_ev"], S.node(5.0, 5, 1 << 3, 6, "player")[HAND_INDEX["65o"]], places=6)
        self.assertEqual(go("A2o", 5, "BB", "BTN allin", players=6, ante="player").action, "CALL")
        # no ante at all is neither game: the solver, as before
        self.assertNotIn("exact", go("65o", 5, "BB", "BTN allin", players=6, ante="none").data)
        with self.assertRaises(ValueError):
            go("65o", 5, "BB", "BTN allin", players=6, ante="each")

    def test_an_ante_near_an_eighth_is_read_from_it_and_says_so(self):
        h, cards = parse_hand("A8o")
        spot = P.quick_spot(h, cards, 10, 8, "UTG", "", ante="player")
        exact = P.advise(spot)
        self.assertNotIn("read from the solution for an ante", " ".join(exact.numbers))
        spot.setup = HandSetup([2500.0] * 8, 125.0, 250.0, 30.0, 0.0)       # 125/250 with 30 from everybody: 0.12 of a big blind
        spot.field_prizes = spot.prizes = Prizes()
        near = P.advise(spot)
        self.assertAlmostEqual(near.data["shove_ev_bb"], exact.data["shove_ev_bb"], places=6)
        self.assertIn("read from the solution for an ante of 0.125bb from every player; here it is 0.12bb", " ".join(near.numbers))
        self.assertEqual(near.warnings, [])
        # a quarter of a big blind from everybody is nobody's solved game: the solver answers, and warns at this depth
        spot.setup = each(3, players=8, ante=0.25)
        far = P.advise(spot)
        self.assertNotIn("exact", far.data)
        self.assertIn("reads weak hands too well", " ".join(far.warnings))
        self.assertIn("an eighth of a big blind from every player", " ".join(far.warnings))

    def test_the_quick_command_takes_the_ante(self):
        import io
        from contextlib import redirect_stdout
        from poker_coach.cli import main

        def quick(*more):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["quick", "--hand", "A8o", "--stack", "3", "--pos", "UTG", "--players", "8", "--goal", "chips", *more])
            self.assertEqual(code, 0)
            return out.getvalue()

        every = quick("--ante", "player")
        self.assertIn("solved exactly", every)
        self.assertNotIn("too well", every)
        self.assertIn("blinds 0.5/1 ante 0.125 ||", every)
        self.assertIn(f"shove EV {S.node(3.0, 0, 0, 8, 'player')[HAND_INDEX['A8o']]:+.2f}bb", every)
        his = quick()
        self.assertIn("blinds 0.5/1 bb-ante 1 ||", his)
        self.assertIn(f"shove EV {S.node(3.0, 1, 0, 9, 'bb')[HAND_INDEX['A8o']]:+.2f}bb", his)       # eight players: the nine's last seats
        self.assertIn("too well", quick("--no-ante"))
        self.assertEqual(quick("--ante", "none"), quick("--no-ante"))

    def test_a_tracked_table_with_real_stacks(self):
        """300 and 600 with 75 from every player, eight players: first in with the shortest stack still to act the
        game is the solved one, and the answer is the table of eight's."""
        stacks = [9000.0, 4200.0, 15000.0, 7000.0, 4200.0, 30000.0, 5100.0, 12000.0]
        setup_ = HandSetup(stacks, 300.0, 600.0, 75.0, 0.0)
        self.assertEqual(S.covered(setup_, 1), 7.0)                     # the second seat holds 7bb and nobody behind holds less
        self.assertIsNone(S.covered(setup_, 0))                         # the first seat has shorter stacks behind
        spot = P.Spot(setup=setup_, hero=1, hand=HAND_INDEX["KJo"])
        adv = P.advise(spot)
        self.assertAlmostEqual(adv.data["shove_ev_bb"], S.node(7.0, 1, 0, 8, "player")[HAND_INDEX["KJo"]], places=6)
        self.assertTrue(adv.data.get("exact"))
        self.assertEqual(S.covered(setup_, 7, [1, 4]), 7.0)             # the two stacks of 4,200 all-in, the big blind to call


if __name__ == "__main__":
    unittest.main()
