"""All-ins of 2 to 20 big blinds: the exact solution (poker_coach/short.py), and the engine reading it.

The data file is made by tools/build_short.py with the solver in tools/aof_solver.c.  Nothing here runs
the solver: the tests hold the stored answers to what any such solution must look like, and hold the
engine to them where the game is theirs.
"""
import json
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_short as BUILD                                    # noqa: E402
from poker_coach import preflop as P                           # noqa: E402
from poker_coach import ranges as R                            # noqa: E402
from poker_coach import short as S                             # noqa: E402
from poker_coach.cards import COMBO_COUNT, HAND_INDEX, HANDS, parse_hand   # noqa: E402
from poker_coach.icm import Prizes, default_payouts            # noqa: E402
from poker_coach.pushfold import HandSetup                     # noqa: E402

SEATS = ("UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO", "BTN", "SB", "BB")
GRID = (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 16.0, 20.0)     # every stack of the push-or-fold zone, and three deeper
PUSH_OR_FOLD = 10.0             # up to here every hand is an all-in or a fold, and the whole answer is the exact game's


def setup(stack, players=9, **kw):
    return HandSetup([float(stack)] * players, 0.5, 1.0, kw.get("ante", 0.0), kw.get("bb_ante", 1.0))


def go(hand, stack, pos, facing="", players=9, opp=None):
    h, cards = parse_hand(hand)
    spot = P.quick_spot(h, cards, stack, players, pos, facing)
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
        self.assertEqual((d["sb"], d["bb"], d["bb_ante"]), (0.5, 1, 1))
        # three passes, and the file says so: every hand 10,000 times; the hands that left near zero ten times
        # that, with two players all-in as well; and first in, the hands that left within two and a half of
        # their standard errors of zero, a million times, kept to a thousandth of a big blind
        self.assertEqual(d["train"], 40_000_000)
        self.assertEqual(d["passes"], [{"samples": 10_000, "all_ins": 2},
                                       {"samples": 100_000, "all_ins": 2, "band": [0.05, 0.04]},
                                       {"samples": 1_000_000, "all_ins": 0, "within": 2.5, "step": 0.001}])
        self.assertEqual(d["passes"], [dict(spec, **({"band": list(spec["band"])} if "band" in spec else {})) for spec in BUILD.PASSES])
        self.assertEqual(S.games(), (3, 4, 5, 6, 9))
        self.assertEqual(S.top(), GRID[-1])
        for players in S.games():
            self.assertEqual(S.stacks(players), GRID, players)
            game = d["games"][str(players)]
            for stack in S.stacks(players):
                nodes = game["nodes"][f"{stack:g}"]
                # every player with nobody, one player or two players all-in before him; the big blind is never first in
                self.assertEqual(len(nodes), sum(1 + i + i * (i - 1) // 2 for i in range(players)) - 1, (players, stack))
                for key, evs in nodes.items():
                    self.assertEqual(len(evs), 169, (players, stack, key))
                # what the seats win and lose in a hand adds up to nothing
                self.assertAlmostEqual(sum(game["value"][f"{stack:g}"]), 0.0, delta=0.02)
                self.assertLess(game["value"][f"{stack:g}"][-1], -0.4)         # the big blind pays for the table
                # the second pass took a part of the hands, not none and not most; the third a few of the hands first in
                second, third = game["again"][f"{stack:g}"]
                self.assertTrue(0.03 * 169 * len(nodes) < second < 0.5 * 169 * len(nodes), (players, stack, second))
                self.assertTrue(0 < third < 0.2 * 169 * (players - 1), (players, stack, third))
                for count, moved in zip((second, third), game["moved"][f"{stack:g}"]):
                    self.assertTrue(0 <= moved < 0.5 * count, (players, stack))
                # a number of the third pass is kept to a thousandth of a big blind, every other to a hundredth
                fine = [key for key, evs in nodes.items() for e in evs if e != int(e)]
                self.assertLessEqual(len(fine), third, (players, stack))
                self.assertEqual({key.split(":")[1] for key in fine} - {"0"}, set(), (players, stack))
        self.assertEqual(S.table_for(6), 6)
        self.assertEqual(S.table_for(8), 9)             # seven and eight players: the last seats of the nine
        self.assertEqual(S.table_for(7), 9)

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
        self.assertIsNone(S.node(3.0, 5, 0, 7))                        # no table of seven was solved


class Playbook(unittest.TestCase):
    def test_the_tables_printed_in_the_playbook_are_the_solution(self):
        """PLAYBOOK.md prints the first-in shares and hands and the calls of an all-in.  Two builds of the data
        differ by a hand here and there, so the rows are made from the data again (tools/short_report.py
        tables) and each must be in the playbook as it stands."""
        import short_report
        with open(os.path.join(ROOT, "PLAYBOOK.md")) as fh:
            text = fh.read()
        rows = [row for row in short_report.tables() if row.startswith("|")]
        self.assertEqual(len(rows), 57)
        for row in rows:
            self.assertIn(row + "\n", text)


class Passes(unittest.TestCase):
    """tools/build_short.py: what the passes after the first do to a solution.  The solver is not run: its
    answers are written here by hand, the way it keeps them."""

    PLAYERS, STACK = 4, 4

    def solution(self):
        """A first pass: at every decision point the hands go from -2.5bb to +2.5bb in steps of 0.03bb, a
        little higher for a later seat, each good to 0.03bb."""
        nodes = []
        for player in range(self.PLAYERS):
            for mask in range(1 << player):
                if player == self.PLAYERS - 1 and mask == 0:
                    continue
                evs = [3 * (c - 84) + player for c in range(169)]
                node = {"player": player, "mask": mask, "freq": [100 if e > 0 else 0 for e in evs], "ev": evs, "samples": 10_004}
                if bin(mask).count("1") <= S.MOST_ALL_IN:
                    node["se_milli"] = [30] * 169
                nodes.append(node)
        return {"n": self.PLAYERS, "stacks": [self.STACK] * self.PLAYERS, "bb_ante": 1, "train": BUILD.TRAIN, "nodes": nodes}

    def keep(self, folder, number, hands, value, error, samples=None):
        """The solver's answer for a later pass, as tools/aof_solver.c prints it."""
        samples = samples or BUILD.PASSES[number - 1]["samples"]
        by_node = {}
        for player, mask, c in hands:
            node = by_node.setdefault((player, mask), {"player": player, "mask": mask, "ev": [0] * 169, "samples": 0,
                                                       "ev_milli": [0.0] * 169, "se_milli": [0.0] * 169, "n": [0] * 169})
            node["ev_milli"][c], node["se_milli"][c], node["n"][c] = value(player, mask, c), error, samples + 4
            node["ev"][c] = int(round(node["ev_milli"][c] / 10.0))
        with open(os.path.join(folder, f"n{self.PLAYERS}_s{self.STACK}.pass{number}.json"), "w") as fh:
            json.dump({"n": self.PLAYERS, "samples": samples, "all_ins": BUILD.PASSES[number - 1]["all_ins"], "stream": number,
                       "nodes": list(by_node.values())}, fh)

    def test_a_later_pass_takes_the_hands_the_one_before_left_near_zero(self):
        import tempfile
        sol = self.solution()
        first = {(nd["player"], nd["mask"]): list(nd["ev"]) for nd in sol["nodes"]}
        # the second pass: within 0.05bb and 0.04bb a big blind of zero, at every decision point that is kept
        near = BUILD.near_zero(sol)
        self.assertAlmostEqual(BUILD.band(self.STACK), 0.21)
        kept = [key for key in first if bin(key[1]).count("1") <= S.MOST_ALL_IN]
        self.assertEqual(len(kept), 13)                         # with three players all-in before the big blind: not kept
        self.assertEqual(sorted(near), sorted((i, m, c) for i, m in kept for c in range(169) if abs(first[i, m][c]) < 21))
        self.assertEqual(len(near), 175)                        # 13 or 14 hands a decision point; 0.21bb itself is not within
        self.assertEqual({bin(m).count("1") for _, m, _ in near}, {0, 1, 2})
        # it finds every number 0.02bb lower than the first did, good to 0.01bb
        second = lambda i, m, c: 10.0 * first[i, m][c] - 20.0                               # noqa: E731
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, f"n{self.PLAYERS}_s{self.STACK}.json")
            with self.assertRaises(SystemExit):                 # no solver, and nothing kept: it says so
                BUILD.fine(None, self.solution(), path, False)
            self.keep(folder, 2, near, second, 10.0)
            # the third: first in, the hands the second left within two and a half standard errors (0.025bb) of zero
            third = [(i, m, c) for i, m, c in near if m == 0 and abs(second(i, m, c)) < 25.0]
            self.assertEqual(sorted(third), [(0, 0, 84), (0, 0, 85), (1, 0, 84), (1, 0, 85), (2, 0, 84)])   # 0.00 to 0.04bb at first
            self.keep(folder, 3, third, lambda i, m, c: second(i, m, c) + 12.34, 3.0)
            did = BUILD.fine(None, sol, path, False)
            self.assertEqual(did["again"], [len(near), 5])
            now = {(nd["player"], nd["mask"]): nd["ev"] for nd in sol["nodes"]}
            for i, m, c in near:
                if (i, m, c) in third:                          # the third pass's number, to a thousandth of a big blind
                    self.assertAlmostEqual(now[i, m][c], first[i, m][c] - 2 + 1.2, places=9)
                else:
                    self.assertEqual(now[i, m][c], first[i, m][c] - 2)
            untouched = [(key, c) for key in first for c in range(169) if (key[0], key[1], c) not in set(near)]
            self.assertTrue(all(now[key][c] == first[key][c] for key, c in untouched))
            # how many hands each pass moved to the other side of zero: 0.01 and 0.02bb became -0.01 and 0.00, and
            # the third pass brought back the two it took of them
            self.assertEqual(did["moved"][0], sum(1 for i, m, c in near if first[i, m][c] in (1, 2)))
            self.assertEqual(did["moved"][1], 2)
            # in from one seat and out from the next, before and after each pass (here a later seat is always higher)
            self.assertEqual(did["crossed"], [0, 0, 0])
            # what the numbers each pass left are good to: [the middle one, the largest], by players all-in before
            self.assertEqual(did["noise"], [[[0.03, 0.03]] * 3, [[0.01, 0.01]] * 3, [[0.003, 0.003]]])
            # the band is seven of the first pass's standard errors here, at each kind of decision point
            self.assertEqual(did["ratio"], [[7.0, 7.0, 7.0], None])
            # the repository keeps the solver's output packed with xz: read the same
            import lzma
            for name in os.listdir(folder):
                with open(os.path.join(folder, name), "rb") as fh, lzma.open(os.path.join(folder, name + ".xz"), "wb") as out:
                    out.write(fh.read())
                os.remove(os.path.join(folder, name))
            packed = self.solution()
            self.assertEqual({k: v for k, v in BUILD.fine(None, packed, path, False).items() if k != "seconds"},
                             {k: v for k, v in did.items() if k != "seconds"})
            self.assertEqual(packed["nodes"], sol["nodes"])
            self.assertEqual(BUILD.read(os.path.join(folder, f"n{self.PLAYERS}_s{self.STACK}.pass2.json"))["stream"], 2)
            self.assertIsNone(BUILD.kept(os.path.join(folder, "n9_s2.json")))
            # a kept answer made with other deals, or for other hands, is not this pass's
            self.keep(folder, 3, third, lambda i, m, c: 0.0, 3.0, samples=500_000)
            with self.assertRaises(SystemExit):
                BUILD.fine(None, self.solution(), path, False)
            self.keep(folder, 3, third[:-1], lambda i, m, c: 0.0, 3.0)
            with self.assertRaises(SystemExit):
                BUILD.fine(None, self.solution(), path, False)

    def test_the_solvers_output_is_packed_into_the_folder_the_repository_keeps(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as kept:
            sol = self.solution()
            names = [f"n{self.PLAYERS}_s{self.STACK}.json", f"n{self.PLAYERS}_s{self.STACK}.pass2.json"]
            for name in names + ["aof_solver", f"n{self.PLAYERS}_s{self.STACK}.strategy.txt", "n9_s8_notes.json"]:
                with open(os.path.join(work, name), "w") as fh:
                    json.dump(sol, fh)
            before, BUILD.KEPT = BUILD.KEPT, kept
            try:
                said = io.StringIO()
                with contextlib.redirect_stdout(said):
                    BUILD.pack(work)
                    BUILD.pack(work)                    # nothing has changed: nothing is written again
            finally:
                BUILD.KEPT = before
            self.assertEqual(sorted(os.listdir(kept)), sorted(name + ".xz" for name in names))      # the solver's own output, no more
            self.assertEqual(BUILD.read(os.path.join(kept, names[0])), sol)
            self.assertRegex(said.getvalue(), r"packed 2 files into .*\(2 kept\)\npacked 0 files")

    def test_a_hand_in_from_a_seat_and_out_from_the_next_is_counted(self):
        sol = self.solution()
        nodes = {(nd["player"], nd["mask"]): nd for nd in sol["nodes"]}
        self.assertEqual(BUILD.crossed(nodes, self.PLAYERS), 0)
        nodes[0, 0]["ev"][10], nodes[1, 0]["ev"][10] = 1, 0          # in first to act, worth nothing from the next seat
        self.assertEqual(BUILD.crossed(nodes, self.PLAYERS), 1)
        nodes[1, 0]["ev"][20], nodes[2, 0]["ev"][20] = 5, -5         # the button and the small blind are not compared
        self.assertEqual(BUILD.crossed(nodes, self.PLAYERS), 1)

    def test_a_kept_first_pass_must_be_this_game_and_this_solver(self):
        sol = self.solution()
        BUILD.check(sol, "kept", self.PLAYERS, self.STACK, BUILD.TRAIN)
        for change in ({"n": 5}, {"bb_ante": 0}, {"train": BUILD.TRAIN // 20}, {"stacks": [5] * self.PLAYERS}):
            with self.assertRaises(SystemExit):
                BUILD.check(dict(sol, **change), "kept", self.PLAYERS, self.STACK, BUILD.TRAIN)
        del sol["nodes"][0]["se_milli"]                     # a solution of the solver before it kept standard errors
        with self.assertRaises(SystemExit):
            BUILD.check(sol, "kept", self.PLAYERS, self.STACK, BUILD.TRAIN)


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

    # First in, the hands that are in from one seat and out from the next, as this build has them after its last
    # pass: the most at a stack of nine players, by stack, and in all the stacks of each smaller table.
    CROSSED = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 1, 9: 0, 10: 3, 12: 1, 16: 4, 20: 7}
    CROSSED_SMALL = {6: 1, 5: 4, 4: 0, 3: 0}
    APART = 0.16            # big blinds: the two numbers of the widest such pair are 0.153 apart (A2s with 20bb)

    def test_a_hand_that_goes_in_from_a_seat_goes_in_from_the_next(self):
        """Nearly so, and most of what is left is the solution's own.  After the first pass alone three to
        eighteen hands a stack were in from one seat and out from the next, 103 in the twelve stacks; a
        chart with that in it reads as a mistake.  The second pass leaves 17, none of them under 9bb.  The
        third deals the first-in hands still nearest zero a million times, and 16 are left: it took the
        noise away and showed that the rest is not noise.  Ten of the sixteen pairs are three to seven
        standard errors apart.  With 10bb the lojack moves in with K8s and T8s and the hijack does not; with
        16 and 20bb a first seat moves in with small suited aces, KJo or KQo that lose up to 0.13bb from the
        next.  Ten of the sixteen hands were there in the build before this one, which was trained on its
        own.  The seats' ranges are built differently (the second seat of nine with 20bb: pairs from 99 and
        every suited ace but A6s; the third: pairs from 55, the suited aces from A9s and A5s), and the
        players behind call the later seat with more hands (PLAYBOOK.md).  With 17bb or more no table moves
        all-in on such a number."""
        with open(os.path.join(ROOT, "poker_coach", "data", "short.json")) as fh:
            games = json.load(fh)["games"]
        for stack in S.stacks():
            odd = []
            for player in range(6):                     # up to the cutoff and the button; the small blind is another game
                here, behind = S.node(stack, player, 0), S.node(stack, player + 1, 0)
                odd += [(SEATS[player], HANDS[h], here[h], behind[h]) for h in range(169) if here[h] > 0 >= behind[h]]
            self.assertEqual(len(odd), games["9"]["crossed"][f"{stack:g}"][-1], (stack, odd))       # the file's own count
            self.assertLessEqual(len(odd), self.CROSSED[int(stack)], (stack, odd))
            for _, _, mine, next_one in odd:            # worth next to nothing from both seats
                self.assertLess(mine - next_one, self.APART, (stack, odd))
        # the smaller tables, from their own solutions: the file's count is the count, and it is what it was
        for players, most in self.CROSSED_SMALL.items():
            total = 0
            for stack in S.stacks(players):
                odd = sum(1 for player in range(players - 3) for a, b in zip(S.node(stack, player, 0, players), S.node(stack, player + 1, 0, players))
                          if a > 0 >= b)
                self.assertEqual(odd, games[str(players)]["crossed"][f"{stack:g}"][-1], (players, stack))
                total += odd
            self.assertLessEqual(total, most, players)
        # what the passes were for: the file keeps the count after each, and no pass raised it
        for players, game in games.items():
            first, second, third = (sum(game["crossed"][f"{stack:g}"][k] for stack in S.stacks(int(players))) for k in range(3))
            self.assertTrue(first >= second >= third, (players, first, second, third))
        first, second, third = (sum(games["9"]["crossed"][f"{stack:g}"][k] for stack in S.stacks()) for k in range(3))
        self.assertGreater(first, 4 * third)

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

    def test_and_the_games_that_were_not(self):
        self.assertIsNone(S.covered(setup(S.top() + 1), 0))             # deeper: the engine's own solver
        self.assertIsNone(S.covered(setup(1.5), 0))
        self.assertIsNone(S.covered(setup(3, players=2), 0))            # heads-up: the engine is exact there
        self.assertIsNone(S.covered(setup(3, ante=0.125, bb_ante=0.0), 0))      # every player antes: another game
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
                # range (a tenth less at 20bb, as the deeper tables take him): the exact answer, moved by that.
                # A hand that is a call or near one is no better against the fewer hands.  (A hand far from a
                # call can be: with 20bb the first seat's tenth is A9s and KQo, and K9o, which KQo had dominated,
                # has half a point more against the rest.)
                self.assertLess(abs(mine - ev), 1.5, (HANDS[hand], stack, SEATS[hero], facing))
                if ev > -1.0:
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
        """About one and a half times the noise, and 0.05bb at least: it grows with the stack, and with two
        players all-in before, where three stacks swing, it is a third wider."""
        self.assertEqual((S.close(5), S.close(10), S.close(20)), (0.05, 0.05, 0.1))
        self.assertEqual((S.close(5, 2), S.close(10, 2), S.close(20, 2)), (0.05, 0.065, 0.13))
        self.assertEqual(P._exact_conf(0.04, 8, 1), "close")
        self.assertEqual(P._exact_conf(0.12, 8, 1), "standard")
        self.assertEqual(P._exact_conf(0.05, 8, 2), "close")
        self.assertEqual(P._exact_conf(0.12, 8, 2), "standard")        # it was close while the first pass stood there
        self.assertEqual(P._exact_conf(0.12, 20, 2), "close")
        self.assertEqual(P._exact_conf(0.2, 20, 2), "standard")        # clear starts at twice the band
        self.assertEqual(P._exact_conf(0.3, 20, 2), "clear")
        # the noise is the one the data file keeps: what the numbers the second pass left are good to, the
        # middle one of them, at every stack of every table, with one player all-in before and with two
        with open(os.path.join(ROOT, "poker_coach", "data", "short.json")) as fh:
            d = json.load(fh)
        for players, game in d["games"].items():
            for stack in S.stacks(int(players)):
                for count in (1, 2):
                    if game["noise"][f"{stack:g}"][1][count] is None:           # three players, a stack with no such hand near zero
                        continue
                    typical, largest = game["noise"][f"{stack:g}"][1][count]
                    self.assertGreaterEqual(S.close(stack, count), 1.4 * typical, (players, stack, count))
                    self.assertLessEqual(S.close(stack, count), max(0.05, 2.0 * typical), (players, stack, count))
                    self.assertGreater(S.close(stack, count), 1.15 * largest, (players, stack, count))
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


if __name__ == "__main__":
    unittest.main()
