#!/usr/bin/env python3
"""Build the All-In or Fold trainer page from the solved tables.

    python3 tools/build_aof_page.py [body-only-output.html]

Writes ``aof_trainer.html`` at the repository root: one self-contained file
that opens in any browser, offline.  With an argument it also writes the page
body alone, the form a hosted page wrapper expects.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    with open(os.path.join(ROOT, "poker_coach", "data", "aof.json")) as fh:
        raw = json.load(fh)
    data: dict = {}
    for sol in raw["solutions"]:
        stack = f"{sol['stack']:g}"
        data.setdefault(sol["family"], {}).setdefault(str(sol["n"]), {})[stack] = {
            "value": sol["value"],
            "nodes": {key: node["e"] for key, node in sol["nodes"].items()},
        }
    with open(os.path.join(ROOT, "tools", "aof_trainer_template.html")) as fh:
        body = fh.read().replace("/*DATA*/", json.dumps(data, separators=(",", ":")))
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n</head>\n'
            '<body style="margin:0">\n' + body + "</body>\n</html>\n")
    out = os.path.join(ROOT, "aof_trainer.html")
    with open(out, "w") as fh:
        fh.write(page)
    print(f"wrote {out} ({len(page) / 1024:.0f} KB)")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as fh:
            fh.write(body)
        print(f"wrote {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
