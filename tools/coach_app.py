"""Entry point of the packaged program (see tools/build_exe.py).

No arguments: the launcher window (set up, teach, start).  With arguments: the
command line, as ``python3 -m poker_coach``, e.g. ``PokerCoach.exe live-test --image shot.png``.
"""
import sys


def run() -> int:
    if len(sys.argv) > 1:
        from poker_coach.cli import main
        return main(sys.argv[1:])
    from poker_coach.live.wizard import launcher
    return launcher()


if __name__ == "__main__":
    raise SystemExit(run())
