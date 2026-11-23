#!/usr/bin/env python3
"""The quick guide's page against the engine, in a real browser: random spots at their real table size.

    python3 tools/check_guide_page.py             # 700 spots, about two minutes
    python3 tools/check_guide_page.py 200 7       # another number of spots, another seed

Each spot is a table of two to nine players, a seat, a stack, a style, a kind of opponent, what happened
before you (nothing, an all-in, two all-ins with 20bb or less, a raise of a size that has a table of its
own with or without callers, players who only called) and a hand that is not a pair (a table puts the
pairs in order).  The page is opened in headless Chromium and asked through its own script
(``window.MenloGuide.answer``), so its choice of table, of seat names at that table size and of stack is
part of what is checked; the engine is asked the same spot in words at that table size
(``poker_coach.preflop.advise``).  The play and whether it is close must be the same.

Needs node with the playwright package and its Chromium (``npm install playwright``,
``npx playwright install chromium``).  It is not one of the tests: they ask the page's script without a
browser (tests/test_guide.py).
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_guide as B                                    # noqa: E402
from poker_coach import preflop as P                       # noqa: E402
from poker_coach import ranges as R                        # noqa: E402
from poker_coach.cards import HANDS                        # noqa: E402

PAGE = os.path.join(ROOT, "guide", "index.html")
ASK = """
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('file://' + process.argv[3]);
  await page.waitForFunction(() => window.MenloGuide && document.querySelector('#guide .foot'));
  const foot = await page.evaluate(() => [...document.querySelectorAll('#guide .foot')].map((e) => e.textContent).filter((t) => t.includes('tables v')).join(' '));
  const answers = await page.evaluate((cs) => cs.map((c) => window.MenloGuide.answer(c.st, c.hand)), cases);
  await browser.close();
  console.log(JSON.stringify({foot, errors, answers}));
})();
"""


def spots(count: int, seed: int) -> list[dict]:
    """Spots as the page has them ("st"), the hand, and the same spot in the engine's words ("facing")."""
    rng = random.Random(seed)
    cases = []
    while len(cases) < count:
        n = rng.choice((2, 3, 4, 5, 6, 6, 7, 8, 8, 9, 9, 9))
        stack = rng.choice(B.STACKS if rng.random() < 0.35 else [s for s in B.STACKS if s <= 20])
        line = rng.choice(("open", "open", "allin", "allin", "two_allin", "raise", "limp"))
        st = {"players": n, "stack": stack, "style": rng.choice(B.STYLES), "opp": rng.choice(B.OPPONENTS), "line": line}
        hand = rng.choice([h for h in HANDS if len(h) == 3])
        seat = lambda nb: R.position_name(nb, n)                                # noqa: E731
        if line == "open":
            st["seat"] = rng.randrange(1, n)
            facing = ""
        elif line == "allin":
            st["seat"] = rng.randrange(0, n - 1)
            st["from"] = rng.randrange(st["seat"] + 1, n)
            facing = f"{seat(st['from'])} allin"
        elif line == "two_allin":           # the second all-in is the seat after the first, as the page draws it
            if n < 3 or stack > 20:         # deeper, the table is made for the big blind and four first seats
                continue
            st["seat"] = rng.randrange(0, n - 2)
            st["from"] = rng.randrange(st["seat"] + 2, n)
            facing = f"{seat(st['from'])} allin, {seat(st['from'] - 1)} allin"
        elif line == "raise":
            st["seat"] = rng.randrange(0, n - 1)
            st["from"] = rng.randrange(st["seat"] + 1, n)
            st["callers"] = rng.choice((0, 0, 0, 1, 2)) if n > 2 else 0
            st["size"] = rng.randrange(len(B.RAISE_SIZES))
            size = B.RAISE_SIZES[st["size"]]
            if st["from"] - st["seat"] - 1 < st["callers"] or not B.own_table(size, stack, st["callers"]):
                continue
            facing = ", ".join([f"{seat(st['from'])} raise {size}bb"] + [f"{seat(st['from'] - k)} call" for k in range(1, st["callers"] + 1)])
        else:
            if n < 3:
                continue
            st["seat"] = rng.randrange(1, n - 1)                # not the big blind: its callers sit elsewhere
            st["limpers"] = rng.choice((1, 1, 2, 3))
            if st["seat"] + st["limpers"] > n - 1:
                continue
            facing = ", ".join(f"{seat(st['seat'] + k)} limp" for k in range(st["limpers"], 0, -1))
        cases.append({"st": st, "hand": hand, "facing": facing})
    return cases


def engine(case: dict) -> tuple[str, bool]:
    st = case["st"]
    R.set_style(st["style"])
    spot = P.quick_spot(HANDS.index(case["hand"]), None, float(st["stack"]), st["players"],
                        R.position_name(st["seat"], st["players"]), case["facing"])
    spot.types = [st["opp"]] * st["players"]
    letter = B.code_of(P.advise(spot))
    return B.ACTIONS[(B.CODES + B.CLOSE).index(letter) % len(B.CODES)], letter in B.CLOSE


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 700
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    cases = spots(count, seed)
    with tempfile.TemporaryDirectory() as folder:
        with open(os.path.join(folder, "cases.json"), "w") as fh:
            json.dump(cases, fh)
        with open(os.path.join(folder, "ask.js"), "w") as fh:
            fh.write(ASK)
        try:
            # the global node_modules too: the script lies in a folder of its own
            env = dict(os.environ)
            found = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
            env["NODE_PATH"] = os.pathsep.join(p for p in (env.get("NODE_PATH"), found) if p)
            done = subprocess.run(["node", os.path.join(folder, "ask.js"), os.path.join(folder, "cases.json"), PAGE],
                                  capture_output=True, text=True, env=env)
        except FileNotFoundError:
            raise SystemExit("node is not installed: this check opens the page in Chromium through node's playwright package")
        if done.returncode:
            raise SystemExit(f"the page could not be asked:\n{done.stderr.strip()}")
        page = json.loads(done.stdout)
    wrong, kinds, read, exact = [], {}, {}, 0
    for case, mine in zip(cases, page["answers"]):
        want = engine(case)
        kinds[case["st"]["line"]] = kinds.get(case["st"]["line"], 0) + 1
        if mine:
            read[mine["from"]] = read.get(mine["from"], 0) + 1
            exact += bool(mine["exact"])
        if mine is None or (mine["name"], bool(mine["close"])) != want:
            wrong.append((case, mine, want))
    print(f"{page['foot'].strip()}; errors on the page: {len(page['errors'])}")
    print(f"{len(cases)} spots: " + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())))
    print(f"read from {len(read)} sets of tables, {exact} spots from a table of the exact solution")
    print(f"{len(wrong)} where the page and the engine differ")
    for case, mine, want in wrong:
        print(f"   {case['st']} {case['hand']}: the page {mine}, the engine {want}")
    return 1 if wrong or page["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
