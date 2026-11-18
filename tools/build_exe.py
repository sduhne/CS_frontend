"""Build the coach as one program that runs without Python or the internet.

Run it on the computer it is for (PyInstaller builds for the system it runs on):

    pip install pyinstaller
    python tools/build_exe.py            # dist/PokerCoach.exe on Windows (dist/PokerCoach elsewhere)
    python tools/build_exe.py --check    # build, then start the program and ask it what a browser would
    python tools/build_exe.py --console  # keep a console window: the address is printed, Ctrl+C stops it

Double-clicked, the program starts the table app (``poker_coach/app``) and opens its page in
the browser.  Everything it decides with is inside it: the engine, the solved tables in
``poker_coach/data`` and the page with its fonts in ``poker_coach/app/static``.  It keeps its
sessions in ``PokerCoach/app`` in the home folder.

It is built without a console window, so the table app shows a small window with a Stop
button (see tools/coach_app.py).  That window needs tkinter; where Python has none, the
program is built with a console instead, and closing the console stops it.

With arguments the program runs the command line, as ``python -m poker_coach``.  That is how
the old screen reader stays reachable: ``PokerCoach.exe live-app``.  It is inside only when
its libraries are installed while building (``pip install -r requirements-live.txt``); the
table app needs none of them.  The Claude vision reader is left out (it would need the
network and a key).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Folders of files (not code) the program reads while it runs.  Each keeps its place: the code
# looks for them beside itself (``os.path.dirname(__file__)``), frozen or not.
DATA_FOLDERS = ("poker_coach/data", "poker_coach/app/static")

READER_LIBRARIES = ("PIL", "mss", "pydantic", "tkinter")        # what the old screen reader needs; the table app needs none


def installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def has_tkinter() -> bool:
    """tkinter is two parts, and an installation can lack either."""
    return installed("tkinter") and installed("_tkinter")


def pyinstaller_problem() -> str:
    """Why this PyInstaller cannot build the program, or "" when it can.

    Version 6 is needed for the window-less program: there ``sys.stdout`` is ``None``, which is
    how tools/coach_app.py knows it has to show its Stop window.  Older versions put a stand-in
    there, and the program would run with no way to stop it.
    """
    if not installed("PyInstaller"):
        return "PyInstaller is not installed: pip install pyinstaller"
    import PyInstaller

    version = getattr(PyInstaller, "__version__", "0")
    if not version.split(".")[0].isdigit() or int(version.split(".")[0]) < 6:
        return f"PyInstaller {version} is too old, version 6 or newer is needed: pip install -U pyinstaller"
    return ""


def pyinstaller_command(name: str = "PokerCoach", onedir: bool = False, console: bool = False,
                        extra: tuple = ()) -> list[str]:
    """The PyInstaller call that builds the program."""
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", name,
           "--onedir" if onedir else "--onefile",
           "--console" if console else "--windowed"]
    for folder in DATA_FOLDERS:
        source = os.path.join(REPO, *folder.split("/"))
        cmd += ["--add-data", f"{source}{os.pathsep}{folder}"]
    cmd += ["--paths", REPO, "--collect-submodules", "poker_coach"]
    if installed("PIL") and has_tkinter():
        cmd += ["--hidden-import", "PIL._tkinter_finder"]       # the screen reader draws its pictures in tkinter windows
    cmd += ["--exclude-module", "anthropic", "--exclude-module", "httpx", "--exclude-module", "numpy",
            "--distpath", os.path.join(REPO, "dist"), "--workpath", os.path.join(REPO, "build"),
            "--specpath", os.path.join(REPO, "build"),
            os.path.join(REPO, "tools", "coach_app.py")]
    return cmd + [x for x in extra if x != "--"]


def program_path(name: str = "PokerCoach", onedir: bool = False) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    return os.path.join(REPO, "dist", name, exe) if onedir else os.path.join(REPO, "dist", exe)


# --------------------------------------------------------------------------
# The check: start the built program and ask it what a browser would
# --------------------------------------------------------------------------

def check_program(program: str, patience: float = 120.0) -> bool:
    """Start the program as the table app on a free port, with a folder of its own, and talk to it.

    It must serve the page and its fonts, take a new session and a deal in each mode, and answer
    each deal with advice: that needs the page, the fonts and the solved tables inside it.
    Prints one line per step; True when every step passed.  The user's own sessions are not touched.
    """
    import http.client
    import json
    import shutil
    import socket
    import tempfile
    import time

    with socket.socket() as probe:                          # a port nobody uses right now
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    work = tempfile.mkdtemp(prefix="pokercoach-check-")
    folder, unpacked = os.path.join(work, "tables"), os.path.join(work, "unpacked")
    os.makedirs(unpacked)
    # A one-file program unpacks itself into the temporary folder and cannot tidy up when it is
    # ended from outside: it is given a temporary folder of its own, removed at the end.
    env = dict(os.environ, TMP=unpacked, TEMP=unpacked, TMPDIR=unpacked)
    nowhere = subprocess.DEVNULL
    running = subprocess.Popen([program, "app", "--no-browser", "--port", str(port), "--folder", folder],
                               stdin=nowhere, stdout=nowhere, stderr=nowhere, env=env)

    def ask(method: str, path: str, intent: dict | None = None):
        """One request -> (status, content type, body).  http.client never goes through a proxy."""
        link = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        try:
            body = json.dumps(intent).encode() if intent is not None else None
            link.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            answer = link.getresponse()
            return answer.status, answer.getheader("Content-Type") or "", answer.read()
        finally:
            link.close()

    def step(what: str, passed: bool, detail: str = "") -> bool:
        line = f"  {'ok    ' if passed else 'FAILED'}  {what}{': ' + detail if detail else ''}"
        print(line.encode("ascii", "replace").decode(), flush=True)     # a console of any code page can show it
        return bool(passed)

    def checks():
        started, waited = time.time(), None
        while waited is None:                               # one file unpacks itself first: that takes a moment
            try:
                waited = ask("GET", "/api/view")
            except (OSError, http.client.HTTPException):
                if running.poll() is not None:
                    yield step("the program starts", False, f"it ended at once (exit code {running.returncode})")
                    return
                if time.time() - started > patience:
                    yield step("the program starts", False, f"no answer on port {port} after {patience:.0f} seconds")
                    return
                time.sleep(0.25)
        status, kind, body = waited
        yield step(f"the program starts and answers on 127.0.0.1:{port} ({time.time() - started:.1f} s)",
                   status == 200 and kind == "application/json" and "mode" in json.loads(body))
        status, kind, body = ask("GET", "/")
        yield step("the page", status == 200 and kind.startswith("text/html") and b"<title>" in body, f"{len(body):,} bytes")
        for name in ("app.css", "render.js", "controller.js", "app.js"):
            status, kind, body = ask("GET", "/" + name)
            with open(os.path.join(REPO, "poker_coach", "app", "static", name), "rb") as fh:
                yield step(name, status == 200 and body == fh.read(), kind)
        fonts = os.path.join(REPO, "poker_coach", "app", "static", "fonts")
        for name in sorted(n for n in os.listdir(fonts) if n.endswith(".woff2")):
            status, kind, body = ask("GET", "/fonts/" + name)
            with open(os.path.join(fonts, name), "rb") as fh:
                yield step("font " + name, status == 200 and kind == "font/woff2" and body == fh.read())
        for mode in ("tournament", "spin", "aof"):
            status, kind, body = ask("POST", "/api/intent", {"op": "new_session", "mode": mode})
            started_session = json.loads(body)
            status, kind, body = ask("POST", "/api/intent", {"op": "deal", "hero_cards": "AhKd"})
            dealt = json.loads(body)
            if "error" in started_session or "error" in dealt or not dealt["view"]["hand"]:
                yield step(f"{mode}: a new session and a deal", False, str(dealt.get("error") or started_session.get("error")))
                continue
            status, kind, body = ask("GET", f"/api/advice?rev={dealt['view']['rev']}")
            advice = json.loads(body)
            verb = (advice.get("headline") or {}).get("verb", "")
            yield step(f"{mode}: a new session, a deal and the coach's answer",
                       advice.get("status") == "ready" and verb not in ("", "NO ADVICE"),
                       f"{verb or advice.get('status')}  ({advice.get('spot') or advice.get('reason', '')})")
        saved = sorted(os.listdir(folder))
        yield step("the sessions are saved", saved == ["aof.json", "app.json", "spin.json", "tournament.json"], ", ".join(saved))

    print(f"checking {program}", flush=True)
    try:
        results = list(checks())
    except Exception as err:                                # an answer that is not what the app sends
        results = [step("the check itself", False, f"{type(err).__name__}: {err}")]
    finally:
        stop(running)
        shutil.rmtree(work, ignore_errors=True)
    return all(results)


def stop(running: subprocess.Popen) -> None:
    """End the program that was started for the check, and what it started."""
    if running.poll() is not None:
        return
    if os.name == "nt":
        # one-file programs are two processes on Windows (the unpacker and the program): end both
        subprocess.call(["taskkill", "/F", "/T", "/PID", str(running.pid)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        running.terminate()
    try:
        running.wait(15)
    except subprocess.TimeoutExpired:
        running.kill()


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--console", action="store_true", help="keep a console window (the address is printed, Ctrl+C "
                    "stops it, and the command line's output shows)")
    ap.add_argument("--onedir", action="store_true", help="a folder instead of one file (starts faster)")
    ap.add_argument("--name", default="PokerCoach")
    ap.add_argument("--check", action="store_true", help="after building, start the program and check that it "
                    "serves the page, the fonts and the coach's answers")
    ap.add_argument("--check-only", action="store_true", help="check the program that is already built")
    ap.add_argument("extra", nargs=argparse.REMAINDER, help="after --: more PyInstaller options")
    a = ap.parse_args()
    program = program_path(a.name, a.onedir)
    shown = os.path.relpath(program, REPO)
    if a.check_only:
        if not os.path.exists(program):
            print(f"{shown} is not built yet: run this without --check-only")
            return 1
        return 0 if check_program(program) else 1
    problem = pyinstaller_problem()
    if problem:
        print(problem)
        return 1
    console = a.console
    if not console and not has_tkinter():
        print("This Python has no tkinter, so the program cannot show its Stop window: building it with a "
              "console window instead (closing that window stops it).")
        console = True
    missing = [m for m in READER_LIBRARIES if not installed(m)]
    if missing:
        print(f"Not installed: {', '.join(missing)}. The program is built without the old screen reader "
              "(pip install -r requirements-live.txt to include it). The table app needs none of them.")
    cmd = pyinstaller_command(a.name, a.onedir, console, tuple(a.extra))
    print(subprocess.list2cmdline(cmd), flush=True)
    done = subprocess.call(cmd, cwd=REPO)
    if done != 0:
        return done
    how_to_stop = "closing its console window stops it" if console else "its small window has the Stop button"
    print(f"\nbuilt {shown}: double-click it to start the table app ({how_to_stop})")
    if a.check and not check_program(program):
        print("\nThe program was built but did not pass the check above.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
