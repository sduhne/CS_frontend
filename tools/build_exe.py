"""Build the coach as one program that runs without Python or the internet.

Run it on the computer it is for (PyInstaller builds for the system it runs on):

    pip install pyinstaller pillow mss pydantic
    python tools/build_exe.py            # dist/PokerCoach.exe on Windows (dist/PokerCoach elsewhere)
    python tools/build_exe.py --console  # keep a console window, to see the command line's output

The program opens the launcher (set up, teach, start).  Everything it decides
with is inside it: the engine, the solved tables and the local screen reader.
The Claude vision reader is left out (it would need the network and a key).
Its files (settings, the reader's layout and book, session logs) go to a
``PokerCoach`` folder in the home folder.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--console", action="store_true", help="keep a console window (shows the command line's output)")
    ap.add_argument("--onedir", action="store_true", help="a folder instead of one file (starts faster)")
    ap.add_argument("--name", default="PokerCoach")
    ap.add_argument("extra", nargs=argparse.REMAINDER, help="after --: more PyInstaller options")
    a = ap.parse_args()
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed: pip install pyinstaller")
        return 1
    data = os.path.join(REPO, "poker_coach", "data")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", a.name,
           "--onedir" if a.onedir else "--onefile",
           "--console" if a.console else "--windowed",
           "--add-data", f"{data}{os.pathsep}poker_coach/data",
           "--paths", REPO,
           "--hidden-import", "PIL._tkinter_finder",
           "--collect-submodules", "poker_coach",
           "--exclude-module", "anthropic", "--exclude-module", "httpx", "--exclude-module", "numpy",
           "--distpath", os.path.join(REPO, "dist"), "--workpath", os.path.join(REPO, "build"),
           "--specpath", os.path.join(REPO, "build"),
           os.path.join(REPO, "tools", "coach_app.py")] + [x for x in a.extra if x != "--"]
    print(" ".join(cmd))
    done = subprocess.call(cmd, cwd=REPO)
    if done == 0:
        exe = a.name + (".exe" if os.name == "nt" else "")
        print(f"\nbuilt {os.path.join('dist', exe)}: double-click it to open the launcher")
    return done


if __name__ == "__main__":
    raise SystemExit(main())
