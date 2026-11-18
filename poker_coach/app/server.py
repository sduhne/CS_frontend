"""The local server of the table app.

    python -m poker_coach app [--port N] [--no-browser] [--verbose]

It serves the page and the three addresses the page talks to:

    GET  /                   the page and its files, from poker_coach/app/static/
    GET  /api/view           everything the page draws (``model.Session.view``)
    POST /api/intent         one change as JSON, such as {"op": "deal"}.  The answer is
                             {"view": ...}, or {"error": {"message", "fix"}, "view": ...} when the
                             change is refused (status 200 both times: the page shows the message)
    GET  /api/advice?rev=N   the coach's answer for revision N of the view, or {"status": "stale"}
                             when the table has changed since.  Without rev: the current revision

The rules it keeps:

- It listens on 127.0.0.1 only and answers only requests addressed to 127.0.0.1 or localhost on
  its own port.  Nothing here reads the screen, clicks for the user or reaches the network.
- One lock guards the session.  The coach's answer is worked out on a private copy of the
  session, outside that lock, so typing the next action never waits for the engine.
- An answer belongs to one revision of the table and is kept until the table changes.
- The advice adapter (``advice.py``) is imported when the first answer is asked for.  If it
  cannot be loaded, or it fails, the answer is {"status": "none"} with the error text, and the
  table goes on working.

The model saves the session after every accepted change, in ``tournament/app/`` (the packaged
program: ``~/PokerCoach/app/``).  Standard library only.
"""

from __future__ import annotations

import copy
import json
import os
import socketserver
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .model import ModelError, Session

DEFAULT_PORT = 8765
PORT_TRIES = 20                         # when the port is taken: how many ports are tried, counting up
MAX_BODY = 1_000_000                    # bytes: the biggest intent accepted (a pasted blind ladder is a few hundred)
IDLE_SECONDS = 30                       # a connection that sends nothing is dropped after this long

STATIC_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Files are served only with these endings.  The table is written out because the system's own
# list (the ``mimetypes`` module) is wrong on some Windows machines, where .js comes out as text.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".txt": "text/plain; charset=utf-8",
}
JSON_TYPE = "application/json"
TEXT_TYPE = "text/plain; charset=utf-8"

# Sent with every answer: the page may load from, and talk to, this program only.  If the page's
# code ever asked another site for something, the browser would refuse and say so in its console.
PAGE_POLICY = ("default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
               "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")

# The adapter's function that answers a session.  The first of these names found in advice.py is used.
ADAPTER_FUNCTIONS = ("advise", "advice_for", "advise_session")

STALE = {"status": "stale"}


# ==========================================================================
# 1. The coach's answer
# ==========================================================================

def load_adapter():
    """The advice adapter's function ``f(session) -> dict``.

    Imported here, not at the top of the file: the server must start, and the table must work,
    even when the adapter is missing or broken.
    """
    from . import advice as adapter

    for name in ADAPTER_FUNCTIONS:
        if callable(getattr(adapter, name, None)):
            return getattr(adapter, name)
    raise ImportError("advice.py has none of these functions: " + ", ".join(ADAPTER_FUNCTIONS))


def snapshot_of(session: Session) -> Session:
    """A private copy of the session for the coach to read while the real one goes on changing.

    Same table, same hand, same settings; it never saves anything.
    """
    twin = Session(folder=session.folder, save=False)
    twin.app = dict(session.app)
    twin.data = copy.deepcopy(session.data)
    return twin


def coach_unavailable(err: Exception) -> dict:
    """What the page gets when the adapter cannot answer: nothing to advise, and why."""
    text = f"{type(err).__name__}: {err}"
    return {"status": "none", "spot": "The coach could not answer: " + text, "error": text}


# ==========================================================================
# 2. The app: one session, its lock, and the answer for the revision on screen
# ==========================================================================

class TableApp:
    """What the server serves.  The three methods are the three ``/api`` addresses.

    ``folder`` is where the session files are (tests pass a temporary one), ``static`` the
    folder of the page, ``coach`` a function ``f(session) -> dict`` to use instead of the
    advice adapter (tests), ``verbose`` prints the adapter's errors in full.
    """

    def __init__(self, folder: str | None = None, static: str | None = None, coach=None, verbose: bool = False):
        # One model.Session holds all three modes: each mode has its own file in the folder,
        # and the session keeps the table of the mode on screen.
        self.session = Session(folder)
        self.lock = threading.Lock()            # guards the session; held only for quick work, never for the engine
        self.advice_lock = threading.Lock()     # one answer is worked out at a time
        self.static = static or STATIC_FOLDER
        self.coach = coach
        self.verbose = verbose
        self._advice_rev = None                 # the revision the kept answer belongs to
        self._advice = None

    def view(self) -> dict:
        with self.lock:
            return self.session.view()

    def rev(self) -> int:
        with self.lock:
            return self.session.rev

    def intent(self, intent) -> dict:
        """Carry out one change.  A refused change leaves everything as it was and says why."""
        with self.lock:
            try:
                return {"view": self.session.apply(intent)}
            except ModelError as err:
                return {"error": {"message": err.message, "fix": err.fix}, "view": self.session.view()}
            except OSError as err:
                # The session file could not be written (on Windows another program may hold it
                # for a moment).  The page gets the table as it stands; the next change saves again.
                return {"error": {"message": f"The session could not be saved ({err}).",
                                  "fix": f"Check that {self.session.folder} can be written."},
                        "view": self.session.view()}

    def advice(self, rev: int) -> dict:
        """The coach's answer for revision ``rev``, or ``{"status": "stale"}`` when the table has moved on."""
        with self.lock:
            known = self._known_answer(rev)
        if known is not None:
            return known
        # One answer is worked out at a time.  A second request for the same revision waits here
        # and then finds the answer ready; one that went stale while waiting is sent away at once.
        with self.advice_lock:
            with self.lock:
                known = self._known_answer(rev)
                if known is None:
                    snapshot = snapshot_of(self.session)
            if known is not None:
                return known
            answer = self._ask_the_coach(snapshot)          # the engine runs here: the session is not locked
            answer["rev"] = rev
            with self.lock:
                if rev != self.session.rev:
                    return STALE                            # the table changed while the engine was thinking
                self._advice_rev, self._advice = rev, answer
                self._keep_for_history(rev, answer)
            return answer

    def _known_answer(self, rev: int):
        """Stale, or the answer already made for this revision, or ``None``: it has to be worked out.

        Call it with the lock held.
        """
        if rev != self.session.rev:
            return STALE
        if rev == self._advice_rev:
            return self._advice
        return None

    def _ask_the_coach(self, session: Session) -> dict:
        """Call the advice adapter.  Never raises: a failure becomes ``{"status": "none"}`` with the error."""
        try:
            coach = self.coach or load_adapter()
            answer = coach(session)
            if not isinstance(answer, dict):
                raise TypeError(f"the adapter returned {type(answer).__name__}, not a dict")
            json.dumps(answer, allow_nan=False)             # it must be something the page can read
            return answer
        except Exception as err:                            # whatever went wrong, the table goes on working
            if self.verbose:
                print_traceback()
            return coach_unavailable(err)

    def _keep_for_history(self, rev: int, answer: dict) -> None:
        """Tell the session what the coach showed, so the hand history can say "deviated"."""
        headline = answer.get("headline") or {}
        if answer.get("status") != "ready" or not headline.get("verb") or headline.get("tone") == "wait":
            return                                          # nothing was advised
        try:
            self.session.record_advice(rev, headline["verb"], headline.get("follow"))
        except Exception:                                   # the answer still goes to the page
            if self.verbose:
                print_traceback()


def print_traceback() -> None:
    if sys.stderr is not None:                              # the packaged program may have no console
        traceback.print_exc()


# ==========================================================================
# 3. Files of the page
# ==========================================================================

def find_static_file(root: str, url_path: str):
    """The file under ``root`` that a URL path names, or ``None``.

    Every part of the path must be the exact name of something that really is in the folder.
    A directory listing never contains "..", so a path cannot climb out of ``root``; a folder
    is not a file, so nothing is ever listed.
    """
    parts = [part for part in url_path.split("/") if part] or ["index.html"]
    folder = root
    try:
        for part in parts[:-1]:
            if part not in os.listdir(folder):
                return None
            folder = os.path.join(folder, part)
            if not os.path.isdir(folder):
                return None
        if parts[-1] not in os.listdir(folder):
            return None
    except OSError:                                         # no such folder
        return None
    path = os.path.join(folder, parts[-1])
    return path if os.path.isfile(path) else None


# ==========================================================================
# 4. The HTTP side
# ==========================================================================

class BadRequest(Exception):
    """A request that cannot be read: answered with this status and message."""

    def __init__(self, status: int, message: str, fix: str = ""):
        super().__init__(message)
        self.status, self.message, self.fix = status, message, fix


class Handler(BaseHTTPRequestHandler):
    server_version = "MenloCoach"
    sys_version = ""
    timeout = IDLE_SECONDS
    disable_nagle_algorithm = True          # a small answer leaves at once instead of waiting to be bundled
    started = None                          # when this request began, for the log

    @property
    def app(self) -> TableApp:
        return self.server.app

    # ---- the three kinds of request --------------------------------------------------

    def do_GET(self) -> None:
        self._answer(self._get)

    def do_HEAD(self) -> None:              # like GET; ``_send`` leaves the body out
        self._answer(self._get)

    def do_POST(self) -> None:
        self._answer(self._post)

    def _answer(self, route) -> None:
        """Run one request.  A failure inside the program becomes a 500 with the reason, not a silence."""
        self.started = time.perf_counter()
        try:
            if self._host_is_ours():
                route()
        except BadRequest as err:
            self._send_error(err.status, err.message, err.fix)
        except (ConnectionError, TimeoutError):
            pass                            # the browser closed the connection, or stopped half-way
        except Exception as err:
            print_traceback()               # a fault of the program: worth seeing even without --verbose
            try:
                self._send_error(500, f"The program failed on this request ({type(err).__name__}: {err}).",
                                 "Reload the page. If it happens again, restart the program.")
            except (ConnectionError, TimeoutError):
                pass

    def _get(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/api/view":
            self._send_json(200, self.app.view())
        elif url.path == "/api/advice":
            self._send_json(200, self.app.advice(self._rev_asked(url.query)))
        elif url.path == "/api/intent":
            raise BadRequest(405, "A change is sent with POST.", 'POST {"op": "..."} to /api/intent.')
        elif url.path.startswith("/api/"):
            raise BadRequest(404, f"There is no {url.path}.", "The addresses are /api/view, /api/intent and /api/advice.")
        else:
            self._send_file(url.path)

    def _post(self) -> None:
        if not self._origin_is_ours():
            return
        url = urlsplit(self.path)
        if url.path != "/api/intent":
            raise BadRequest(404 if url.path not in ("/api/view", "/api/advice") else 405,
                             f"Nothing can be sent to {url.path}.", "Changes go to /api/intent.")
        self._send_json(200, self.app.intent(self._json_body()))

    # ---- who is asking -----------------------------------------------------------------

    def _own_names(self) -> tuple[str, str]:
        port = self.server.server_port
        return f"127.0.0.1:{port}", f"localhost:{port}"

    def _host_is_ours(self) -> bool:
        """Answer only requests addressed to this computer under its own name.

        A page on another site can point a name of its own at 127.0.0.1 and have the browser
        call it; such a request still carries the other name in its Host line.
        """
        host = (self.headers.get("Host") or "").strip().lower()
        if host in self._own_names():
            return True
        self._send(403, TEXT_TYPE, f"Refused: this is the poker coach on http://{self._own_names()[0]}/ "
                                   "and the request was addressed to another host.\n".encode())
        return False

    def _origin_is_ours(self) -> bool:
        """A change must come from the coach's own page.

        The browser names the page a POST comes from in the Origin line; a page of another site
        is refused.  A program (curl, a test) sends no Origin and is let through.
        """
        origin = self.headers.get("Origin")
        if origin is None or origin.strip().lower() in ["http://" + name for name in self._own_names()]:
            return True
        self._send_error(403, "Refused: the change was sent by a page of another site.", "")
        return False

    # ---- reading the request -------------------------------------------------------------

    def _rev_asked(self, query: str) -> int:
        text = parse_qs(query).get("rev", [""])[0].strip()
        if not text:
            return self.app.rev()           # no revision named: the table as it is now
        try:
            return int(text)
        except ValueError:
            raise BadRequest(400, f"rev must be a whole number, not {text!r}.",
                             "Send the rev of the view on screen.") from None

    def _json_body(self):
        fix = 'Send one JSON object, such as {"op": "deal"}.'
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            raise BadRequest(400, "The request does not say how long it is.", fix)
        if length > MAX_BODY:
            raise BadRequest(413, "The request is too big.", fix)
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:                  # not UTF-8, or not JSON
            raise BadRequest(400, "The request is not JSON.", fix) from None

    # ---- answering --------------------------------------------------------------------------

    def _send_file(self, url_path: str) -> None:
        path = find_static_file(self.app.static, unquote(url_path))
        content_type = CONTENT_TYPES.get(os.path.splitext(path)[1].lower()) if path else None
        if content_type is None:
            if url_path in ("/", "/index.html"):
                message = (f"The page is missing: {os.path.join(self.app.static, 'index.html')} was not found. "
                           "The server itself is running: /api/view answers.\n")
            else:
                message = f"Not found: {url_path}\n"
            self._send(404, TEXT_TYPE, message.encode("utf-8"))
            return
        with open(path, "rb") as fh:
            body = fh.read()
        # no-cache: the browser asks again every time, so an edited file shows on the next reload
        self._send(200, content_type, body, cache="no-cache")

    def _send_json(self, status: int, content: dict) -> None:
        body = json.dumps(content, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self._send(status, JSON_TYPE, body)

    def _send_error(self, status: int, message: str, fix: str = "") -> None:
        self._send_json(status, {"error": {"message": message, "fix": fix}})

    def _send(self, status: int, content_type: str, body: bytes, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", PAGE_POLICY)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---- the log ------------------------------------------------------------------------------

    def log_message(self, format, *args) -> None:
        """One line per request on stderr, and only with ``--verbose``."""
        if not self.server.verbose or sys.stderr is None:
            return
        took = f" {(time.perf_counter() - self.started) * 1000:.0f} ms" if self.started else ""
        line = "".join(ch if ch.isprintable() else "?" for ch in format % args)     # what was sent, made safe to print
        sys.stderr.write(f"{time.strftime('%H:%M:%S')} {line}{took}\n")


class TableServer(ThreadingHTTPServer):
    """The HTTP server: a thread per request, this computer only."""

    daemon_threads = True                   # Ctrl+C does not wait for a browser's idle connections
    # "Reuse address" lets the program restart at once on the same port.  On Windows it would
    # also let two programs listen on one port, so there it stays off.
    allow_reuse_address = os.name != "nt"

    def __init__(self, port: int, app: TableApp, verbose: bool = False):
        self.app = app
        self.verbose = verbose
        super().__init__(("127.0.0.1", port), Handler)

    def server_bind(self) -> None:
        # The usual version also looks up this computer's network name, which can take seconds
        # on some machines and is not needed here.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address) -> None:
        """A connection that broke off (a closed tab, a cancelled request) is not news."""
        if self.verbose:
            print_traceback()


def start_server(port: int = DEFAULT_PORT, folder: str | None = None, verbose: bool = False,
                 static: str | None = None, coach=None) -> TableServer:
    """Open the server on ``port``, or on the next free port after it (0: any free port).

    It is listening when this returns; ``serve_forever()`` starts the answering.
    """
    if not 0 <= port <= 65535:
        raise ValueError(f"the port must be between 0 and 65535, not {port}")
    app = TableApp(folder, static, coach, verbose)
    problem = None
    for candidate in range(port, min(port + PORT_TRIES, 65536)):
        try:
            return TableServer(candidate, app, verbose)
        except OSError as err:
            problem = err                   # taken, or not allowed: try the next one
    raise OSError(f"no free port from {port} to {min(port + PORT_TRIES, 65536) - 1} ({problem})")


def main(port: int = DEFAULT_PORT, open_browser: bool = True, verbose: bool = False,
         folder: str | None = None) -> int:
    """Start the table app and serve it until Ctrl+C."""
    server = start_server(port, folder, verbose)
    address = f"http://127.0.0.1:{server.server_port}/"
    moved = f" (port {port} was taken)" if port and server.server_port != port else ""
    print(f"Menlo Coach is running at {address}{moved}. Ctrl+C stops it.", flush=True)
    if open_browser:
        # in a thread of its own: some systems take a moment to hand the address to the browser
        threading.Thread(target=webbrowser.open, args=(address,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.app.lock:               # a change that is being saved right now is finished first
            server.server_close()
    return 0
