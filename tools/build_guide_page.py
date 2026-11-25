"""Put the quick guide's page into one file, for publishing as a Claude Artifact.

    python3 tools/build_guide_page.py <out folder>

The page itself is guide/ (index.html, guide.css, guide.js, data.js, fonts): that folder is what a web server
serves, and it opens from the disk as it is.  An Artifact is one HTML file without <html>, <head> or <body>,
which takes its type from Google Fonts and may bring other files along.  This writes that file
(menlo-guide.html: the styles and the script inside it) and copies the tables beside it (data.json), which
the script fetches when the page has no ``window.GUIDE_DATA``, and the Spin & Go tables (spin.json), which it
fetches the first time that game is chosen.
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "guide")
FONTS = ("https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:ital,wght@0,700;0,800;1,800"
         "&family=Inter:wght@400;500;600;700&display=swap")


def page() -> str:
    with open(os.path.join(GUIDE, "guide.css")) as fh:
        css = fh.read()
    with open(os.path.join(GUIDE, "guide.js")) as fh:
        js = fh.read()
    if "</script" in js.lower() or "</style" in css.lower():
        raise SystemExit("the script or the styles hold a closing tag: they cannot go inside the page as they are")
    return f"""<title>Menlo Guide</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="{FONTS}">
<style>
{css}</style>
<div id="guide" class="guide"><p class="loading">Loading the tables&hellip;</p></div>
<script>
{js}</script>
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.split("\n\n")[1].strip())
        return 2
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "menlo-guide.html"), "w") as fh:
        fh.write(page())
    names = ["menlo-guide.html"]
    for name in ("data.json", "spin.json"):
        if os.path.exists(os.path.join(GUIDE, name)):
            shutil.copyfile(os.path.join(GUIDE, name), os.path.join(out, name))
            names.append(name)
    for name in names:
        print(f"{os.path.getsize(os.path.join(out, name)) / 1e6:6.2f} MB  {os.path.join(out, name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
