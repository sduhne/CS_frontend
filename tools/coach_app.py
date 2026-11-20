"""Entry point of the packaged program (see tools/build_exe.py).

    PokerCoach.exe                   the table app: it starts and opens its page in the browser
    PokerCoach.exe --port 9000       the same with options (--port, --folder, --no-browser, --verbose)
    PokerCoach.exe live-app          the old screen reader's launcher (set up, teach, start)
    PokerCoach.exe <command> ...     any other command of ``python -m poker_coach`` ("app" is the table app)

The table app keeps its sessions in ``PokerCoach/app`` in the home folder.

Two things differ from ``python -m poker_coach app``:

- A program built without a console window (the default on Windows) cannot print and has no
  Ctrl+C.  The table app then shows a small window with the address, "Open the page" and
  "Stop"; Stop, or closing that window, ends the program.  With a console (``build_exe.py
  --console``) the address is printed and Ctrl+C or closing the console ends it.
- Started while a copy already serves the same folder of tables, it opens that copy's page and
  steps aside: two copies would save over each other's tables.  The server finds the running
  copy (``server.start_server`` raises ``AlreadyRunning``), so this holds for every way of
  starting: with or without a console, on any port, with ``--folder`` or without.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser

if not getattr(sys, "frozen", False):       # run as "python tools/coach_app.py": the package is one folder up
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TITLE = "Menlo Coach"                       # the program's name wherever it speaks: as server.PROGRAM and the page's title
NOTICE = "For study and play money. Real-money sites ban real-time help."


def run(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["app"] + argv               # no command (nothing at all, or only options): the table app
    if argv[0] == "app":
        return table_app(argv)
    from poker_coach.cli import main
    return main(argv)


def has_console() -> bool:
    """False in a program built without a console window: ``sys.stdout`` and ``sys.stderr`` are ``None`` there."""
    return sys.stdout is not None and sys.stderr is not None


def tell(text: str) -> None:
    """Say something to the user: printed when there is a console, a message box when there is none."""
    if has_console():
        print(text, file=sys.stderr)
        return
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(TITLE, text)
        root.destroy()
    except Exception:                       # no tkinter in this build, or no screen: there is nowhere to say it
        pass


# --------------------------------------------------------------------------
# The table app
# --------------------------------------------------------------------------

def table_app(argv) -> int:
    from poker_coach.cli import build_parser, main

    if has_console():
        return main(argv)                   # exactly "python -m poker_coach app": Ctrl+C stops it
    return table_app_with_a_window(build_parser().parse_args(argv))


def table_app_with_a_window(options) -> int:
    """The table app of a program without a console: serve the page until the small window is closed."""
    from poker_coach.app import server
    from poker_coach.cli import app_folder

    try:
        table = server.start_server(options.port, app_folder(options.folder), options.verbose)
    except server.AlreadyRunning as running:
        # Started twice.  The copy that is running keeps the tables; this one shows its page and ends.
        if not options.no_browser:
            webbrowser.open(running.address)
        return 0
    except (OSError, ValueError) as err:    # no free port, or a folder that cannot be used
        tell(f"{TITLE} could not start.\n\n{err}")
        return 2
    address = f"http://127.0.0.1:{table.server_port}/"
    threading.Thread(target=table.serve_forever, daemon=True).start()
    if not options.no_browser:
        # in a thread of its own: some systems take a moment to hand the address to the browser
        threading.Thread(target=webbrowser.open, args=(address,), daemon=True).start()
    try:
        stop_window(address, table.app.session.folder)
    finally:
        table.shutdown()
        with table.app.lock:                # a change that is being saved right now is finished first
            table.server_close()
    return 0


def stop_window(address: str, folder: str) -> None:
    """The small window: where the page is, where the tables are saved, Open the page, Stop.

    It returns when Stop is pressed or the window is closed.
    """
    try:
        import tkinter

        root = tkinter.Tk()
    except Exception:
        # No tkinter in this build, or no screen.  The page still works; the program runs until
        # it is ended from outside (Windows: Task Manager, PokerCoach).
        threading.Event().wait()
        return
    root.title(TITLE)
    root.resizable(False, False)
    lines = (("The table app is running.", ("Segoe UI", 12, "bold")),
             (f"Its page:  {address}", None),
             (f"Your tables are saved in:  {folder}", None))
    for text, font in lines:
        tkinter.Label(root, text=text, font=font, anchor="w", justify="left").pack(fill="x", padx=16, pady=(12, 0))
    buttons = tkinter.Frame(root)
    buttons.pack(fill="x", padx=16, pady=14)
    tkinter.Button(buttons, text="Open the page", width=16, command=lambda: webbrowser.open(address)).pack(side="left")
    tkinter.Button(buttons, text="Stop", width=10, command=root.destroy).pack(side="left", padx=10)
    tkinter.Label(root, text="Stop, or closing this window, ends the program.\n" + NOTICE,
                  anchor="w", justify="left").pack(fill="x", padx=16, pady=(0, 14))
    root.mainloop()


if __name__ == "__main__":
    raise SystemExit(run())
