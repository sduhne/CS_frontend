"""How the table app reaches the user: the --folder option, the files to double-click, the build.
Run: python -m unittest tests.test_app_package

Nothing here needs Windows or PyInstaller.  The .bat files are read, not run: what is checked is
their line endings, the command they start and that every "goto" has its label.  The build
script is asked for the PyInstaller call it would make.  The packaged program's entry
(tools/coach_app.py) is run in this process, with the server it starts on a free port.
"""

import http.client
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from poker_coach import cli
from poker_coach.app import model, server

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

START = "Start Poker Coach.bat"
OLD_READER = "Start Screen Reader (old).bat"
BUILD = "Build exe.bat"
GUIDE = "START HERE.txt"


def load_tool(name: str):
    """A script of tools/ as a module (the folder is not a package)."""
    spec = importlib.util.spec_from_file_location("tool_" + name, os.path.join(REPO, "tools", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_exe = load_tool("build_exe")
coach_app = load_tool("coach_app")


def read_bytes(name: str) -> bytes:
    with open(os.path.join(REPO, name), "rb") as fh:
        return fh.read()


def lines_of(name: str) -> list:
    return read_bytes(name).decode("ascii").split("\r\n")


def get(port: int, path: str = "/api/view"):
    """One GET -> (status, the Server line, body)."""
    link = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        link.request("GET", path)
        answer = link.getresponse()
        return answer.status, answer.getheader("Server"), answer.read()
    finally:
        link.close()


def port_is_closed(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(5)
        return probe.connect_ex(("127.0.0.1", port)) != 0


class FolderCase(unittest.TestCase):
    """A temporary folder, and no $POKER_COACH_APP unless the test sets one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="menlo-package-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("POKER_COACH_APP", None)


# --------------------------------------------------------------------------
# python -m poker_coach app --folder <path>
# --------------------------------------------------------------------------

class TheFolderOption(FolderCase):
    def test_the_option(self):
        parse = cli.build_parser().parse_args
        self.assertIsNone(parse(["app"]).folder)
        self.assertEqual(parse(["app", "--folder", "my tables"]).folder, "my tables")

    def test_the_folder_is_handed_to_the_server_as_a_full_path_and_made(self):
        folder = os.path.join(self.tmp, "Poker Coach", "my tables")      # spaces, and it is not there yet
        with mock.patch.object(server, "main", return_value=0) as main:
            self.assertEqual(cli.main(["app", "--folder", folder, "--port", "9001", "--no-browser"]), 0)
        main.assert_called_once_with(port=9001, open_browser=False, verbose=False, folder=folder)
        self.assertTrue(os.path.isdir(folder))

    def test_a_relative_folder_and_the_home_sign(self):
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        self.assertEqual(cli.app_folder(os.path.join("~", "tables")), os.path.join(self.tmp, "tables"))
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.tmp)
        self.assertEqual(os.path.realpath(cli.app_folder("relative")), os.path.realpath(os.path.join(self.tmp, "relative")))
        self.assertIsNone(cli.app_folder(None))
        self.assertIsNone(cli.app_folder(""))

    def test_without_the_option_the_server_chooses(self):
        with mock.patch.object(server, "main", return_value=0) as main:
            cli.main(["app", "--no-browser"])
        main.assert_called_once_with(port=8765, open_browser=False, verbose=False)

    def test_a_folder_that_cannot_be_used_is_said_plainly(self):
        a_file = os.path.join(self.tmp, "a file")
        with open(a_file, "w", encoding="utf-8") as fh:
            fh.write("not a folder")
        with mock.patch.object(server, "main", return_value=0) as main, redirect_stderr(io.StringIO()) as shown:
            self.assertEqual(cli.main(["app", "--folder", a_file]), 2)
        main.assert_not_called()
        self.assertIn("--folder", shown.getvalue())
        self.assertIn(a_file, shown.getvalue())

    def serve_one_change(self, argv):
        """Run the command with one change made and Ctrl+C pressed -> the server it ran."""
        served = []

        def one_change_then_ctrl_c(srv, poll_interval=0.5):
            served.append(srv)
            self.assertNotIn("error", srv.app.intent({"op": "new_session", "mode": "spin"}))
            raise KeyboardInterrupt

        with mock.patch.object(server.TableServer, "serve_forever", one_change_then_ctrl_c), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(argv), 0)
        return served[0]

    def test_the_option_wins_over_the_variable(self):
        named, from_variable = os.path.join(self.tmp, "named"), os.path.join(self.tmp, "variable")
        os.environ["POKER_COACH_APP"] = from_variable
        srv = self.serve_one_change(["app", "--port", "0", "--no-browser", "--folder", named])
        self.assertEqual(srv.app.session.folder, named)
        self.assertIn("spin.json", os.listdir(named))
        self.assertFalse(os.path.exists(from_variable))

    def test_the_variable_wins_over_the_usual_folder(self):
        from_variable = os.path.join(self.tmp, "variable")
        os.environ["POKER_COACH_APP"] = from_variable
        srv = self.serve_one_change(["app", "--port", "0", "--no-browser"])
        self.assertEqual(srv.app.session.folder, from_variable)
        self.assertIn("spin.json", os.listdir(from_variable))

    def test_the_usual_folders(self):
        root = model.S.ROOT
        self.assertEqual(model.default_folder(), os.path.join(root, "tournament", "app"))
        with mock.patch.object(sys, "frozen", True, create=True):         # the packaged program
            self.assertEqual(model.default_folder(), os.path.join(root, "app"))


# --------------------------------------------------------------------------
# The files the user double-clicks
# --------------------------------------------------------------------------

class TheLaunchers(unittest.TestCase):
    def command_lines(self, name: str) -> list:
        """The lines of a .bat that run Python, without the " >nul 2>nul" some end with."""
        return [re.sub(r"\s*>nul 2>nul$", "", line) for line in lines_of(name) if line.startswith("%PY% ")]

    def test_they_are_there_in_plain_ascii_with_windows_line_endings(self):
        for name in (START, OLD_READER, BUILD, GUIDE):
            with self.subTest(name):
                content = read_bytes(name)
                self.assertTrue(content.endswith(b"\r\n"))
                self.assertEqual(content.count(b"\n"), content.count(b"\r\n"), "a line ends without CR")
                self.assertEqual(content.count(b"\r"), content.count(b"\r\n"), "a CR without LF")
                content.decode("ascii")                                 # the Windows console shows any code page's ASCII

    def test_git_leaves_their_line_endings_alone(self):
        with open(os.path.join(REPO, ".gitattributes"), encoding="utf-8") as fh:
            rules = [line.split() for line in fh.read().splitlines() if line.strip()]
        self.assertIn(["*.bat", "-text"], rules)
        self.assertIn(["START?HERE.txt", "-text"], rules)

    def test_every_goto_has_its_label(self):
        for name in (START, OLD_READER, BUILD):
            with self.subTest(name):
                lines = lines_of(name)
                labels = {line[1:].strip().lower() for line in lines if line.startswith(":")}
                jumps = {m.group(1).lower() for line in lines for m in re.finditer(r"\bgoto\s+(\w+)", line)}
                self.assertTrue(jumps)
                self.assertEqual(jumps - labels, set())
                self.assertEqual(lines[0], "@echo off")
                self.assertIn('cd /d "%~dp0"', lines)                   # it runs from its own folder, wherever that is

    def test_a_file_started_from_inside_the_zip_says_so(self):
        """Each looks for a file it needs before anything else, and that file is really there."""
        for name in (START, OLD_READER, BUILD):
            with self.subTest(name):
                lines = lines_of(name)
                guards = [m.group(1) for line in lines for m in re.finditer(r'^if not exist "([^"]+)" goto nofiles$', line)]
                self.assertEqual(len(guards), 1)
                self.assertTrue(os.path.isfile(os.path.join(REPO, *guards[0].split("\\"))), guards[0])
                self.assertLess(lines.index(f'if not exist "{guards[0]}" goto nofiles'), lines.index('set "PY=python"'))
                self.assertIn("Unpack the whole zip first", "\r\n".join(lines))

    def test_the_starter_starts_the_table_app_and_installs_nothing(self):
        text = "\r\n".join(lines_of(START))
        self.assertIn("%PY% -m poker_coach app", self.command_lines(START))
        for word in ("pip", "requirements", "live-app", "install -r"):
            self.assertNotIn(word, text)
        self.assertIn("Python is not installed on this computer.", text)
        self.assertIn("https://www.python.org/downloads/", text)
        self.assertIn("sys.version_info >= (3, 10)", text)              # the engine needs Python 3.10
        self.assertIn("goto oldpython", text)

    def test_the_old_screen_reader_keeps_its_own_starter(self):
        text = "\r\n".join(lines_of(OLD_READER))
        self.assertIn("%PY% -m poker_coach live-app", self.command_lines(OLD_READER))
        self.assertIn("%PY% -m pip install -r requirements-live.txt", self.command_lines(OLD_READER))
        self.assertNotIn("poker_coach app", text)
        self.assertIn("Python is not installed on this computer.", text)
        self.assertTrue(os.path.exists(os.path.join(REPO, "requirements-live.txt")))

    def test_the_builder_runs_the_build_script_and_its_check(self):
        self.assertIn(r"%PY% tools\build_exe.py --check", self.command_lines(BUILD))
        self.assertIn('%PY% -m pip install "pyinstaller>=6"', self.command_lines(BUILD))
        self.assertTrue(os.path.exists(os.path.join(REPO, "tools", "build_exe.py")))

    def test_the_guide_says_the_five_things(self):
        guide = " ".join(" ".join(lines_of(GUIDE)).split())
        for words in ('double-click "Start Poker Coach.bat"',                    # what to double-click
                      "a page in your browser",                                 # what opens
                      "tournament\\app",                                        # where the saved tables are
                      "Close the black window",                                 # how to stop it
                      "STUDY AND PLAY MONEY ONLY",
                      "Real-money sites ban real-time help"):
            self.assertIn(words, guide)
        for name in (START, OLD_READER, BUILD, "README.md", "PLAYBOOK.md"):      # every file it names is there
            self.assertIn(name, guide)
            self.assertTrue(os.path.exists(os.path.join(REPO, name)), name)


# --------------------------------------------------------------------------
# tools/build_exe.py
# --------------------------------------------------------------------------

class TheBuildScript(unittest.TestCase):
    def added_data(self, command: list) -> dict:
        """{place inside the program: source folder} of every --add-data."""
        pairs = [command[i + 1] for i, word in enumerate(command) if word == "--add-data"]
        return {pair.rsplit(os.pathsep, 1)[1]: pair.rsplit(os.pathsep, 1)[0] for pair in pairs}

    def test_t9_the_saved_sessions_check_counts_only_the_json_files(self):
        """The check "the sessions are saved": the folder also holds app.lock and the .bak copies."""
        tmp = tempfile.mkdtemp(prefix="menlo-package-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        running = server.start_server(0, folder=tmp)            # as the program under check: it writes its lock
        self.addCleanup(running.server_close)
        for mode in ("tournament", "spin", "aof"):              # what the check does: a new session and a deal per mode
            running.app.session.apply({"op": "new_session", "mode": mode})
            running.app.session.apply({"op": "deal", "hero_cards": "AhKd"})
        names = os.listdir(tmp)
        self.assertIn("app.lock", names)
        self.assertTrue([name for name in names if name.endswith(".bak")], names)
        self.assertEqual(build_exe.saved_sessions(names), ["aof.json", "app.json", "spin.json", "tournament.json"])
        self.assertEqual(build_exe.saved_sessions(["tournament.json", "app.lock", "tournament.json.bak"]), ["tournament.json"])

    def test_the_page_and_the_solved_tables_go_inside(self):
        data = self.added_data(build_exe.pyinstaller_command())
        self.assertEqual(set(data), {"poker_coach/data", "poker_coach/app/static"})
        for place, source in data.items():
            # each folder keeps its place, because the code looks for it beside itself
            self.assertEqual(os.path.normpath(source), os.path.normpath(os.path.join(REPO, place)))
            self.assertTrue(os.path.isdir(source), source)
        self.assertEqual(os.path.normpath(data["poker_coach/app/static"]), os.path.normpath(server.STATIC_FOLDER))
        static = data["poker_coach/app/static"]
        for name in ("index.html", "app.css", "app.js", "render.js", "controller.js"):
            self.assertTrue(os.path.isfile(os.path.join(static, name)), name)
        fonts = os.listdir(os.path.join(static, "fonts"))
        self.assertEqual(len([name for name in fonts if name.endswith(".woff2")]), 7)
        self.assertEqual(len([name for name in fonts if name.startswith("OFL-")]), 2)    # the fonts' licences travel with them
        tables = os.listdir(data["poker_coach/data"])
        for name in ("aof.json", "binary.json", "latereg.json", "nash_push.json", "preflop_equity.json",
                     "spin.json", "tag.json"):
            self.assertIn(name, tables)

    def test_no_file_of_the_package_is_left_out(self):
        """Every file under poker_coach/ that is not code lies in a folder the build adds."""
        package = os.path.join(REPO, "poker_coach")
        added = [os.path.join(REPO, *place.split("/")) + os.sep for place in build_exe.DATA_FOLDERS]
        for folder, folders, files in os.walk(package):
            folders[:] = [name for name in folders if name != "__pycache__"]
            for name in files:
                path = os.path.join(folder, name)
                if not name.endswith((".py", ".pyc")):
                    self.assertTrue(path.startswith(tuple(added)), f"{path} is not in the packaged program")

    def test_the_program_it_builds(self):
        command = build_exe.pyinstaller_command()
        self.assertEqual(command[:3], [sys.executable, "-m", "PyInstaller"])
        self.assertEqual(command[-1], os.path.join(REPO, "tools", "coach_app.py"))      # the program's entry
        self.assertIn("--onefile", command)
        self.assertIn("--windowed", command)
        self.assertEqual(command[command.index("--name") + 1], "PokerCoach")
        self.assertEqual(command[command.index("--paths") + 1], REPO)
        self.assertEqual(command[command.index("--collect-submodules") + 1], "poker_coach")
        self.assertEqual(command[command.index("--distpath") + 1], os.path.join(REPO, "dist"))
        self.assertIn("anthropic", [command[i + 1] for i, word in enumerate(command) if word == "--exclude-module"])
        with_console = build_exe.pyinstaller_command(console=True, onedir=True, extra=("--", "--log-level", "WARN"))
        self.assertIn("--console", with_console)
        self.assertNotIn("--windowed", with_console)
        self.assertIn("--onedir", with_console)
        self.assertEqual(with_console[-2:], ["--log-level", "WARN"])

    def test_where_the_program_lands(self):
        exe = "PokerCoach.exe" if os.name == "nt" else "PokerCoach"
        self.assertEqual(build_exe.program_path(), os.path.join(REPO, "dist", exe))
        self.assertEqual(build_exe.program_path(onedir=True), os.path.join(REPO, "dist", "PokerCoach", exe))

    def test_an_old_pyinstaller_is_refused(self):
        # before version 6 a program without a console got a stand-in for sys.stdout, not None,
        # and the entry would not know it has to show its Stop window
        for version, fine in (("6.22.3", True), ("6.0.0", True), ("7.1", True), ("5.13.2", False), ("4.10", False)):
            fake = types.ModuleType("PyInstaller")
            fake.__version__ = version
            with mock.patch.dict(sys.modules, {"PyInstaller": fake}), \
                    mock.patch.object(build_exe, "installed", return_value=True):
                problem = build_exe.pyinstaller_problem()
            self.assertEqual(problem == "", fine, version)
            if not fine:
                self.assertIn(version, problem)
        with mock.patch.object(build_exe, "installed", return_value=False):
            self.assertIn("pip install pyinstaller", build_exe.pyinstaller_problem())


# --------------------------------------------------------------------------
# tools/coach_app.py: what the packaged program does when it starts
# --------------------------------------------------------------------------

class ThePackagedProgram(FolderCase):
    def run_program(self, argv, console=True):
        """``coach_app.run`` with the command line stubbed -> (exit code, what the command line was given)."""
        given = []

        def command_line(args):
            given.append(list(args))
            return 0

        with mock.patch.object(cli, "main", command_line), \
                mock.patch.object(coach_app, "has_console", return_value=console):
            return coach_app.run(argv), given

    def test_no_arguments_is_the_table_app(self):
        self.assertEqual(self.run_program([]), (0, [["app"]]))

    def test_only_options_are_the_table_app_s_options(self):
        self.assertEqual(self.run_program(["--port", "9001", "--no-browser"]),
                         (0, [["app", "--port", "9001", "--no-browser"]]))
        self.assertEqual(self.run_program(["app", "--port", "9001"]), (0, [["app", "--port", "9001"]]))

    def test_a_command_runs_the_command_line(self):
        # the old screen reader's launcher stays reachable: PokerCoach.exe live-app
        for argv in (["live-app"], ["advise", "--hand", "AJo"], ["--help"], ["-h"]):
            for console in (True, False):
                self.assertEqual(self.run_program(argv, console), (0, [argv]))

    def test_the_console_is_judged_by_the_two_streams(self):
        self.assertTrue(coach_app.has_console())
        with mock.patch.object(sys, "stdout", None):
            self.assertFalse(coach_app.has_console())
        with mock.patch.object(sys, "stderr", None):
            self.assertFalse(coach_app.has_console())

    def run_without_a_console(self, argv):
        """The table app as a program without a console runs it -> (exit code, what was seen while its window was open)."""
        seen = {"opened": []}
        opened = threading.Event()

        def open_browser(address):
            seen["opened"].append(address)
            opened.set()

        def window(address, folder):                    # stands in for the Stop window: look, then "press Stop"
            seen["address"], seen["folder"] = address, folder
            seen["port"] = int(address.rsplit(":", 1)[1].strip("/"))
            seen["view"] = get(seen["port"])
            seen["page"] = get(seen["port"], "/")
            if "--no-browser" not in argv:
                self.assertTrue(opened.wait(10))

        with mock.patch.object(coach_app, "stop_window", window), \
                mock.patch.object(coach_app.webbrowser, "open", open_browser), \
                mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            code = coach_app.run(argv)
        return code, seen

    def test_without_a_console_it_serves_until_its_window_is_closed(self):
        folder = os.path.join(self.tmp, "tables")
        code, seen = self.run_without_a_console(["--port", "0", "--folder", folder])
        self.assertEqual(code, 0)
        status, name, body = seen["view"]
        self.assertEqual((status, name.strip(), json.loads(body)["mode"]), (200, "MenloCoach", "tournament"))
        self.assertEqual(seen["page"][0], 200)
        self.assertIn(b"<title>", seen["page"][2])
        self.assertEqual(seen["folder"], folder)
        self.assertEqual(seen["opened"], [seen["address"]])
        self.assertTrue(port_is_closed(seen["port"]))                   # closing the window stopped the program

    def test_without_a_console_and_without_the_browser(self):
        os.environ["POKER_COACH_APP"] = os.path.join(self.tmp, "variable")
        code, seen = self.run_without_a_console(["--port", "0", "--no-browser"])
        self.assertEqual((code, seen["opened"]), (0, []))
        self.assertEqual(seen["folder"], os.path.join(self.tmp, "variable"))
        self.assertTrue(port_is_closed(seen["port"]))

    def test_without_a_console_a_start_that_fails_is_told_not_printed(self):
        told = []
        with mock.patch.object(coach_app, "tell", told.append), \
                mock.patch.object(server, "start_server", side_effect=OSError("no free port from 8765 to 8784")), \
                mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            self.assertEqual(coach_app.run([]), 2)
        self.assertEqual(len(told), 1)
        self.assertIn("no free port", told[0])

    def a_running_copy(self, folder=None):
        """A table app on a free port -> (its port, its folder of tables)."""
        folder = folder or os.path.join(self.tmp, "running")
        running = server.start_server(0, folder=folder)
        thread = threading.Thread(target=running.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()

        def stop():
            running.shutdown()
            running.server_close()
            thread.join(5)

        self.addCleanup(stop)
        return running.server_port, folder

    def start_again(self, argv, console):
        """A second start of the program -> (exit code, the pages it opened, what it printed, what it told in a box)."""
        told = []
        with mock.patch.object(coach_app, "stop_window", side_effect=AssertionError("a second copy was started")), \
                mock.patch.object(server.TableServer, "serve_forever",
                                  side_effect=AssertionError("a second copy was started")), \
                mock.patch.object(coach_app, "tell", told.append), \
                mock.patch.object(coach_app, "has_console", return_value=console), \
                mock.patch.object(coach_app.webbrowser, "open") as open_browser, \
                redirect_stdout(io.StringIO()) as printed:
            code = coach_app.run(argv)
        return code, [call.args[0] for call in open_browser.call_args_list], printed.getvalue(), told

    def test_t9_started_twice_it_opens_the_running_copy_s_page_and_ends(self):
        """In every way of starting: a window or a console, the copy's port, another port, the folder by option or variable."""
        port, folder = self.a_running_copy()
        address = f"http://127.0.0.1:{port}/"
        with socket.socket() as free:                   # a port nothing listens on: the folder's lock says where the copy is
            free.bind(("127.0.0.1", 0))
            elsewhere = free.getsockname()[1]
        for argv in (["--folder", folder, "--port", str(port)], ["--folder", folder, "--port", str(elsewhere)],
                     ["app", "--folder", folder, "--port", "0"]):
            for console in (False, True):
                code, opened, printed, told = self.start_again(argv, console)
                self.assertEqual((code, opened, told), (0, [address], []), (argv, console))
                self.assertEqual(f"Menlo Coach is already running at {address}" in printed, console, (argv, console))
        os.environ["POKER_COACH_APP"] = folder          # without --folder: the usual folder is the one being served
        for console in (False, True):
            code, opened, printed, told = self.start_again(["--port", str(elsewhere)], console)
            self.assertEqual((code, opened, told), (0, [address], []), console)
        self.assertEqual(sorted(n for n in os.listdir(folder) if n.endswith(".lock")), ["app.lock"])    # still the first copy's
        self.assertEqual(get(port)[0], 200)             # ... which goes on answering

    def test_t9_started_twice_without_the_browser_it_only_ends(self):
        port, folder = self.a_running_copy()
        for console in (False, True):
            code, opened, printed, told = self.start_again(["--folder", folder, "--no-browser"], console)
            self.assertEqual((code, opened, told), (0, [], []), console)

    def test_t9_a_copy_with_a_folder_of_its_own_is_started_all_the_same(self):
        # a folder of its own means tables of its own: nothing to save over.  Also on the port the first copy has
        port, folder = self.a_running_copy()
        second = os.path.join(self.tmp, "second")
        code, seen = self.run_without_a_console(["--port", str(port), "--folder", second, "--no-browser"])
        self.assertEqual((code, seen["folder"]), (0, second))
        self.assertNotEqual(seen["port"], port)         # the next free port
        self.assertEqual(seen["view"][0], 200)
        argv = ["--port", "9001", "--folder", second, "--no-browser"]
        with mock.patch.object(cli, "main", return_value=0) as command_line:       # with a console: the command line, as it is
            self.assertEqual(coach_app.run(argv), 0)
        command_line.assert_called_once_with(["app"] + argv)

    def test_t9_the_older_check_of_its_own_is_gone(self):
        self.assertFalse(hasattr(coach_app, "coach_is_at"))     # one place decides: server.start_server

    def test_d5_the_window_and_its_message_boxes_say_menlo_coach(self):
        """One name wherever the program speaks: the window's title and "could not start" are the server's name."""
        self.assertEqual(coach_app.TITLE, server.PROGRAM)
        self.assertEqual(coach_app.TITLE, "Menlo Coach")
        told = []
        with mock.patch.object(coach_app, "tell", told.append), \
                mock.patch.object(coach_app, "has_console", return_value=False), \
                mock.patch.object(server, "start_server", side_effect=OSError("no free port from 8765 to 8784")):
            self.assertEqual(coach_app.run(["--no-browser"]), 2)
        self.assertEqual(told, ["Menlo Coach could not start.\n\nno free port from 8765 to 8784"])
        with open(os.path.join(REPO, "tools", "coach_app.py"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("Poker Coach", text)           # (PokerCoach.exe and the PokerCoach folder are file names: they stay)
        self.assertIn("PokerCoach.exe", text)

    def test_the_stop_window(self):
        """The real window, where this Python has tkinter and a screen: Stop closes it."""
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception as err:
            self.skipTest(f"no tkinter window here ({type(err).__name__}: {err})")
        shown = {}

        def press_stop(root, n=0):                      # instead of waiting for the user
            def widgets(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from widgets(child)

            everything = list(widgets(root))
            shown["title"] = root.title()
            shown["labels"] = [w.cget("text") for w in everything if isinstance(w, tkinter.Label)]
            buttons = {w.cget("text"): w for w in everything if isinstance(w, tkinter.Button)}
            shown["buttons"] = sorted(buttons)
            with mock.patch.object(coach_app.webbrowser, "open") as open_browser:
                buttons["Open the page"].invoke()
            shown["opened"] = open_browser.call_args[0][0]
            buttons["Stop"].invoke()

        with mock.patch.object(tkinter.Tk, "mainloop", press_stop):
            coach_app.stop_window("http://127.0.0.1:8765/", os.path.join(self.tmp, "tables"))
        text = " ".join(shown["labels"])
        self.assertEqual((shown["title"], shown["buttons"]), ("Menlo Coach", ["Open the page", "Stop"]))
        self.assertEqual(shown["opened"], "http://127.0.0.1:8765/")
        for words in ("http://127.0.0.1:8765/", os.path.join(self.tmp, "tables"), "Stop", coach_app.NOTICE):
            self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
