#!/usr/bin/env python3
"""Build poker_coach/data/latereg.json: the shove-spot tables of the late-registration system.

    python3 tools/build_latereg.py            # about one minute

For 8-handed tables and each caller profile (loose, normal, tight) it stores,
for every seat and stack depth, the chance that a shove gets through and the
equity when it is called, per hand class.  ``poker_coach.latereg.spots`` reads
them; other table sizes are solved on first use.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from poker_coach import latereg as L  # noqa: E402


def main() -> int:
    data = {"version": 1, "depths": list(L.DEPTHS), "spots": {}}
    for players in (8,):
        for callers in L.CALLERS:
            tab = L.compute_spots(players, callers)
            data["spots"][f"{players}:{callers}"] = {
                "open": {f"{nb}:{d:g}": [L._pack(fe), L._pack(eq)] for (nb, d), (fe, eq) in tab["open"].items()},
                "raise": {f"{d:g}": [L._pack(fe), L._pack(eq)] for d, (fe, eq) in tab["raise"].items()},
            }
            print(f"{players} players, {callers} callers: {len(tab['open'])} open spots", flush=True)
    with open(L._DATA, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"wrote {L._DATA} ({os.path.getsize(L._DATA) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
