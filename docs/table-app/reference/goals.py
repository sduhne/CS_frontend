import sys
sys.path.insert(0, "/tmp/claude-0/-home-user-CS-frontend/aa601cb2-5545-5621-9e0c-8faa1c3fd22d/scratchpad/tableapp")
from h import *
import re
STAGES = [("early", 800), ("middle", 400), ("approach", 260), ("near", 185), ("bubble", 152), ("itm", 100), ("ft", 8)]
def key(adv):
    d = adv.data
    if "shove_ev_bb" in d: return f"ev{d['shove_ev_bb']:+.2f}"
    if "reshove_ev_bb" in d: return f"rs{d['reshove_ev_bb']:+.2f}"
    if "equity" in d: return f"eq{100*d['equity']:.0f}/need{100*d['need']:.0f}"
    return ""
def run(label, stacks, hero, hand, facing=""):
    print(f"\n## {label}")
    for name, rem in STAGES:
        row = []
        for g in ("itm", "balanced", "chips"):
            st = mk(stacks, hero, entrants=1000, remaining=rem, paid=150, start_bb=None, goal=g, avg_bb=None)
            # average stack: total chips = 1000 entrants * 10000 start; bb chosen so avg ~ 25bb mid
            adv, spot, dt = ask(st, hand, facing, show=False)
            row.append(f"{g}: {adv.action[:22]:<22} [{adv.confidence[:5]}] {key(adv)}")
        print(f"{name:<9}| " + " | ".join(row))
# 8-handed order: UTG UTG+1 LJ HJ CO BTN SB BB
run("A8o BTN 12bb first in (blinds 15/20)", [30,25,18,40,22,12,15,20], "BTN", "A8o")
run("K9s CO 14bb first in", [30,25,18,40,14,22,16,28], "CO", "K9s")
run("99 BB 20bb vs CO all-in 15bb (covered by hero)", [30,25,18,40,15,22,16,20], "BB", "99", "s5 allin")
run("AJo BB 18bb vs BTN all-in 25bb (BTN covers hero)", [30,25,18,40,15,25,16,18], "BB", "AJo", "s6 allin")
run("TT HJ 22bb vs UTG raise 2.2bb", [35,25,18,22,15,25,16,18], "HJ", "TT", "s1 raise 2200")
run("QJs BTN 35bb first in", [30,25,18,40,15,35,16,28], "BTN", "QJs")
