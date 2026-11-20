#!/usr/bin/env python3
"""Play whole 3-player winner-take-all sit & gos with the all-in or fold tables.

    python3 tools/spin_sim.py                 # the matrix stored in spin.json ("sim"), about 6 minutes
    python3 tools/spin_sim.py --games 20000   # quicker and rougher

Every player moves all-in or folds.  Hero reads a table of poker_coach.spin by
the effective stack, exactly as the printed sheet is used; the two opponents
shove the solved ranges and call ``k`` times too many hands (1 = correctly).
The game is GGPoker Spin & Gold: the multiplier sets the starting stack and
the length of a level.  It is played to the last chip with rising blinds,
side pots and real cards, so the result is the share of games hero wins:
33.3% is an even game and 35.9% pays the fee.

What it cannot show: opponents who limp, raise small and play after the flop.
With deep stacks they do better than this against an all-in or fold player.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from poker_coach import binary as BN                                   # noqa: E402
from poker_coach import spin as S                                      # noqa: E402
from poker_coach.cards import COMBO_COUNT, class_of, parse_range       # noqa: E402
from poker_coach.evaluator import evaluate                             # noqa: E402

OUT = os.path.join(ROOT, "poker_coach", "data", "spin.json")

# GGPoker Spin & Gold, three players (ggpoker.com/poker-games/spin-gold and two 2026 guides):
# the multiplier sets the starting stack and the speed.  Blinds are the same in every game.
BLINDS = [(10, 20), (15, 30), (20, 40), (30, 60), (40, 80), (50, 100), (60, 120), (75, 150), (90, 180), (100, 200),
          (125, 250), (150, 300), (200, 400), (250, 500), (300, 600), (400, 800), (500, 1000), (600, 1200),
          (800, 1600), (1000, 2000), (1250, 2500), (1500, 3000)]
HANDS_PER_MINUTE = (3.0, 4.0)        # three-handed, heads-up: an assumption, the site does not publish it
# name -> (starting chips, minutes a level, or 0 when a level is `hands` hands, hands, share of all games)
STRUCTURES = {
    "x2": (300, 1.0, 0, 0.4786),
    "x3": (300, 2.0, 0, 0.4462),
    "x4": (500, 2.0, 0, 0.0265),
    "x5": (500, 3.0, 0, 0.0250),
    "x10": (500, 0.0, 10, 0.0235),
}
HALF = 61                    # effective stacks are looked up in half big blinds, up to 30


def _top(ev: list[float], k: float) -> list[bool]:
    """The best ``k`` times as many hands as have a positive EV."""
    base = sum(c for e, c in zip(ev, COMBO_COUNT) if e > 0)
    take, acc = [False] * 169, 0.0
    for h in sorted(range(169), key=lambda h: -ev[h]):
        if acc >= k * base:
            break
        take[h] = True
        acc += COMBO_COUNT[h]
    return take


def table(kind: str) -> dict[str, list[list[bool]]]:
    """{spot: [range per half big blind]} for a way of playing.

    ``sheet``/``sheet-loose``/``sheet-vloose``: the printed table (one column per stack band).
    ``exact``/``exact-loose``/``exact-vloose``: the engine's answer (nearest solved stack).
    ``mtt``: the all-in or fold tournament tables (6-handed, before the money).
    ``calls:<k>`` / ``shoves:<j>:calls:<k>``: an opponent who calls k times (and shoves j times) as many hands.
    """
    out: dict[str, list[list[bool]]] = {}
    games = S.data()["games"]
    for spot, (n, key, _label, verb) in S.SPOTS.items():
        rows = []
        for half in range(HALF):
            bb = max(1.0, half / 2.0)
            if kind.startswith(("sheet", "exact")):
                vs = kind.partition("-")[2] or "solid"
                stack = S.BANDS[S.band(bb)][1] if kind.startswith("sheet") else bb
                rows.append([w >= 0.5 for w in S.play(spot, stack, vs)])
            elif kind == "mtt":
                rows.append(_mtt(spot, bb))
            elif kind.startswith("margin:"):
                # margin:<profile>:<big blinds>: only the hands that earn at least that much (stored in 0.01bb)
                _m, vs, margin = kind.split(":")
                stack = S.BANDS[S.band(bb)][1]
                ev = games[str(n)][f"{S.nearest(stack):g}"]["ev"][vs][key]
                rows.append([w == 1 for w in S.tidy([e - 100.0 * float(margin) for e in ev])])
            else:
                parts = kind.split(":")
                shove_k = float(parts[parts.index("shoves") + 1]) if "shoves" in parts else 1.0
                call_k = float(parts[parts.index("calls") + 1]) if "calls" in parts else 1.0
                ev = games[str(n)][f"{S.nearest(bb):g}"]["ev"]["solid"][key]
                rows.append(_top(ev, shove_k if verb == "all-in" else call_k))
        out[spot] = rows
    return out


def _mtt(spot: str, bb: float) -> list[bool]:
    if spot in ("btn", "sb", "hu_sb"):
        return [w >= 0.5 for w in BN.first_in_range("before", 2 if spot == "btn" else 1, bb, 6)]
    shover = {"sb_vs_btn": "button", "bb_vs_btn": "button", "bb_vs_sb": "small", "bb_vs_both": "two", "hu_bb": "small"}[spot]
    return [w >= 0.5 for w in parse_range(BN.call(shover, bb, big_blind=spot.startswith(("bb", "hu_bb")), players=6))]


def play_games(args) -> tuple[int, int, int]:
    """(games, games hero won, hands played) for (hero's table, the opponents', the game, games, seed, pace)."""
    hero_kind, opp_kind, structure, games, seed, pace = args
    rng = random.Random(seed)
    hero, opp = table(hero_kind), table(opp_kind)
    start, minutes, fixed, _share = STRUCTURES[structure] if isinstance(structure, str) else structure
    levels = BLINDS
    per3 = fixed or minutes * pace[0]
    per2 = fixed or minutes * pace[1]
    deck = list(range(52))
    wins = hands_total = 0
    for _g in range(games):
        stacks = [start, start, start]
        alive = [0, 1, 2]
        rng.shuffle(alive)                     # alive[0] is the button
        clock = 0.0                            # levels elapsed
        while len(alive) > 1:
            sb, bb = levels[min(int(clock), len(levels) - 1)]
            n = len(alive)
            clock += 1.0 / (per3 if n == 3 else per2)
            hands_total += 1
            cards = rng.sample(deck, 2 * n + 5)
            hole = [(cards[2 * i], cards[2 * i + 1]) for i in range(n)]
            cls = [class_of(*h) for h in hole]
            st = [stacks[p] for p in alive]
            if n == 3:
                posted = [0, min(sb, st[1]), min(bb, st[2])]
            else:
                posted = [min(sb, st[0]), min(bb, st[1])]
            tabs = [hero if p == 0 else opp for p in alive]

            def wants(i: int, spot: str, eff: float) -> bool:
                if st[i] <= posted[i]:
                    return True                 # all-in from the blind
                if eff <= bb:
                    return True                 # nothing left to lose worth folding for
                return tabs[i][spot][min(HALF - 1, int(2.0 * eff / bb + 0.5))][cls[i]]

            if n == 3:
                b = wants(0, "btn", min(st[0], max(st[1], st[2])))
                if b:
                    s = wants(1, "sb_vs_btn", min(st[1], st[0]))
                else:
                    s = wants(1, "sb", min(st[1], st[2]))
                if b and s:
                    g = wants(2, "bb_vs_both", min(st[2], max(st[0], st[1])))
                elif b:
                    g = wants(2, "bb_vs_btn", min(st[2], st[0]))
                elif s:
                    g = wants(2, "bb_vs_sb", min(st[2], st[1]))
                else:
                    g = True                    # a walk
                inn = [b, s, g]
            else:
                s = wants(0, "hu_sb", min(st[0], st[1]))
                g = wants(1, "hu_bb", min(st[1], st[0])) if s else True
                inn = [s, g]
            put = [st[i] if inn[i] else posted[i] for i in range(n)]
            live = [i for i in range(n) if inn[i]]
            if len(live) == 1:
                gain = [0.0] * n
                gain[live[0]] = sum(put)
            else:
                board = cards[2 * n:]
                val = {i: evaluate(list(hole[i]) + board) for i in live}
                gain = [0.0] * n
                prev = 0
                for lvl in sorted({put[i] for i in live}):
                    pot = sum(min(c, lvl) - min(c, prev) for c in put)
                    elig = [i for i in live if put[i] >= lvl]
                    best = max(val[i] for i in elig)
                    top = [i for i in elig if val[i] == best]
                    for i in top:
                        gain[i] += pot / len(top)
                    prev = lvl
                dead = sum(max(0, c - prev) for c in put)       # a folded blind bigger than every all-in
                if dead:
                    biggest = max(live, key=lambda i: put[i])
                    gain[biggest] += dead
            for i, p in enumerate(alive):
                stacks[p] = stacks[p] - put[i] + gain[i]
            alive = [p for p in alive[1:] + alive[:1] if stacks[p] > 1e-9]
        wins += alive[0] == 0
    return games, wins, hands_total


def win_rate(hero: str, opp: str, structure="x2", games: int = 100_000, procs: int = 4, seed: int = 11,
             pace=HANDS_PER_MINUTE) -> tuple[float, float]:
    """(share of games hero wins, hands per game)."""
    chunk = games // procs
    with mp.Pool(procs) as pool:
        res = pool.map(play_games, [(hero, opp, structure, chunk, seed + 7919 * i, pace) for i in range(procs)])
    g = sum(r[0] for r in res)
    return sum(r[1] for r in res) / g, sum(r[2] for r in res) / g


# what the two opponents do: the solved all-in ranges with wider calls, and one passive kind that
# also moves all-in with half as many hands as the solution (it folds the rest)
OPPONENTS = {"solid": "calls:1", "loose": "calls:1.5", "vloose": "calls:2", "passive": "shoves:0.5:calls:1.5"}
HEROES = ("sheet", "sheet-loose", "mtt")


def main() -> int:
    games = int(sys.argv[sys.argv.index("--games") + 1]) if "--games" in sys.argv else 200_000
    t0 = time.time()
    sim: dict = {"games": games, "hands_per_minute": list(HANDS_PER_MINUTE), "blinds": BLINDS,
                 "structures": {k: {"start": v[0], "level_minutes": v[1], "level_hands": v[2], "share": v[3]}
                                for k, v in STRUCTURES.items()}, "results": {}, "pace": {}}
    for structure, (_start, _min, _fixed, share) in STRUCTURES.items():
        res = sim["results"][structure] = {}
        n = games if share > 0.1 else games // 2
        for hero in HEROES:
            for name, opp in OPPONENTS.items():
                w, hands = win_rate(hero, opp, structure, n)
                res[f"{hero}|{name}"] = [round(100 * w, 2), round(hands, 1)]
                print(f"{structure:4} {hero:13} against {name:7}: wins {100 * w:5.2f}%  ({hands:.0f} hands a game, "
                      f"{time.time() - t0:.0f}s)", flush=True)
    # how much the assumed speed of play matters (the two common games, loose opponents)
    for label, pace in (("slow", (2.0, 3.0)), ("fast", (4.0, 5.0))):
        for structure in ("x2", "x3"):
            w, hands = win_rate("sheet-loose", OPPONENTS["loose"], structure, games, pace=pace)
            sim["pace"][f"{label}|{structure}"] = [round(100 * w, 2), round(hands, 1)]
            print(f"{label} pace {structure}: wins {100 * w:5.2f}%  ({hands:.0f} hands a game)", flush=True)
    with open(OUT) as fh:
        data = json.load(fh)
    data["sim"] = sim
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"stored in {OUT} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
