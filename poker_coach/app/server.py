"""The local server of the table app.

    python -m poker_coach app [--port N] [--no-browser] [--verbose] [--folder PATH]

It serves the page and the addresses the page talks to:

    GET  /                   the page and its files, from poker_coach/app/static/
    GET  /api/view           everything the page draws (``model.Session.view``)
    POST /api/intent         one change as JSON, such as {"op": "deal"}.  The answer is
                             {"view": ...}, or {"error": {"message", "fix"}, "view": ...} when the
                             change is refused (status 200 both times: the page shows the message).
                             An intent may carry "rev", the revision of the view it was made on:
                             when the table has changed since, nothing is done and the answer is a
                             409 with {"error": {"code": "stale", ...}, "view": the view as it is}.
                             A body that is not JSON is a 400
    GET  /api/advice?rev=N   the coach's answer for revision N of the view, or {"status": "stale"}
                             when the table has changed since.  Without rev: the current revision
    GET  /api/ping           {"app", "folder", "pid", "port"}: which program this is and whose tables
                             it holds.  A second start asks it, and opens this copy's page instead

The rules it keeps:

- It listens on 127.0.0.1 only and answers only requests addressed to 127.0.0.1 or localhost on
  its own port.  Nothing here reads the screen, clicks for the user or reaches the network.
- One lock guards the session.  The coach's answer is worked out on a private copy of the
  session, outside that lock, so typing the next action never waits for the engine.
- An answer belongs to one revision of the table and is kept until the table changes.
- The advice adapter (``advice.py``) is imported when the first answer is asked for.  If it
  cannot be loaded, or it fails, the answer is {"status": "none"} with the error text, and the
  table goes on working.
- One copy of the program per folder of tables.  A running copy leaves ``app.lock`` (its pid
  and port) beside the session files and takes it away when it stops; a second start on the
  same folder finds it, asks ``/api/ping`` and steps aside (``AlreadyRunning``).  Two copies
  would each keep the tables in memory and save over each other.

One ``model.Session`` holds the three modes, each in its own file (tournament.json, spin.json,
aof.json) beside app.json.  The model saves after every accepted change, in ``tournament/app/``
(the packaged program: ``~/PokerCoach/app/``).  Standard library only.
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
MAX_DROPPED = 8_000_000                 # bytes of a body that is too big which are still read (and thrown away)
IDLE_SECONDS = 30                       # a connection that sends nothing is dropped after this long

APP_NAME = "Poker Coach table app"      # what /api/ping answers: how a second start knows its own kind
LOCK_NAME = "app.lock"                  # in the session folder while a copy of the program serves it
PING_SECONDS = 1                        # how long a start waits for an answer from a copy that may be running

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
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}
JSON_TYPE = "application/json"
TEXT_TYPE = "text/plain; charset=utf-8"

# Sent with every answer: the page may load from, and talk to, this program only.  If the page's
# code ever asked another site for something, the browser would refuse and say so in its console.
PAGE_POLICY = ("default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
               "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")

# The adapter's function that answers a session: ``f(session) -> dict`` in the shape of the
# build spec, section 7.  The first of these names found in advice.py is used.
ADAPTER_FUNCTIONS = ("advise", "advice_for", "advise_session", "get_advice")

STALE = {"status": "stale"}

# A warning with this code says the answer is provisional: charts it needs are still being worked
# out in the background.  Such an answer is not kept, so asking again gets the real one.
PROVISIONAL = "charts_loading"


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
    """What the page gets when the adapter cannot answer: nothing to advise, and (in ``error``) why."""
    text = f"{type(err).__name__}: {err}"
    return {"status": "none", "error": text,
            "spot": "The coach cannot answer this spot. The table goes on working; the next spot is asked again."}


# ==========================================================================
# 2. The app: the session, its lock, and the answer for the revision on screen
# ==========================================================================

class TableApp:
    """What the server serves.  ``view``, ``intent`` and ``advice`` are the three ``/api`` addresses.

    ``folder`` is where the session files are (tests pass a temporary one), ``static`` the
    folder of the page, ``coach`` a function ``f(session) -> dict`` to use instead of the
    advice adapter (tests), ``verbose`` prints the adapter's errors in full.
    """

    def __init__(self, folder: str | None = None, static: str | None = None, coach=None, verbose: bool = False):
        self.session = Session(folder)          # reads the saved files; a missing one is a fresh table
        self.lock = threading.Lock()            # guards the session; held only for quick work, never for the engine
        self.advice_lock = threading.Lock()     # one answer is worked out at a time
        self.static = static or STATIC_FOLDER
        self.coach = coach
        self.verbose = verbose
        self._advice_rev = None                 # the revision the kept answer belongs to
        self._advice = None
        self._warmed = set()                    # table sizes whose all-in charts were already asked for

    # ---- the table ---------------------------------------------------------------------

    def view(self) -> dict:
        with self.lock:
            return self.session.view()

    def rev(self) -> int:
        with self.lock:
            return self.session.rev

    def intent(self, intent) -> dict:
        """Carry out one change.  A refused change leaves everything as it was and says why.

        A change that was made and could not be saved is not a refusal: the view comes back with
        a toast "Made, not saved yet" (``view.unsaved``), and the next change saves again.
        """
        with self.lock:
            try:
                view = self.session.apply(intent)
                self._warm_the_coach(view)
                return {"view": view}
            except ModelError as err:
                if err.code == "unreadable" and self.verbose and sys.stderr is not None:
                    sys.stderr.write(f"unreadable request: {self.session.last_fault}\n")    # the detail, for the log only
                return self._refused(err.message, err.fix, err.code)
            except Exception:
                # A fault in the program, not in what was typed.  The session in memory may be
                # half changed, so it is read again from the files: they hold the table as it
                # was after the last accepted change.
                print_traceback()
                self._read_saved_session()
                return self._refused("The program failed on that change.", "Nothing was changed. Try it another way.")

    def _warm_the_coach(self, view: dict) -> None:
        """The all-in or fold plan reads charts that take seconds to work out the first time.

        They are started on (in a thread of the adapter's own) as soon as that plan is chosen,
        so they are ready long before the first spot that needs them.
        """
        if self.coach is not None or view["mode"] != "tournament" or view["strip"]["plan"] != "allin":
            return
        players = sum(1 for seat in view["table"]["seats"] if not seat["empty"])
        try:
            from . import advice as adapter
            size = adapter.table_players(players)       # the charts exist for a few table sizes
            if size not in self._warmed:
                self._warmed.add(size)
                adapter.bubble_sheet(size)              # returns at once: the work goes on behind
        except Exception:                               # no adapter, or an older one: nothing to warm
            if self.verbose:
                print_traceback()

    def _refused(self, message: str, fix: str, code: str = "") -> dict:
        """``code`` names the few refusals the page reacts to (see ``model.ModelError``); most have none."""
        error = {"message": message, "fix": fix}
        if code:
            error["code"] = code
        return {"error": error, "view": self.session.view()}

    def _read_saved_session(self) -> None:
        try:
            self.session = Session(self.session.folder)
        except OSError:                         # a file is held right now: the session in memory stays
            print_traceback()
        self._advice_rev = self._advice = None

    def ping(self, port: int) -> dict:
        """Which program this is and whose tables it holds (no lock: it answers while a change is made)."""
        return {"app": APP_NAME, "folder": same_folder(self.session.folder), "pid": os.getpid(), "port": port}

    # ---- the coach ---------------------------------------------------------------------

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
                if not is_provisional(answer):
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
            return dict(answer)
        except Exception as err:                            # whatever went wrong, the table goes on working
            if self.verbose:
                print_traceback()
            return coach_unavailable(err)

    def _keep_for_history(self, rev: int, answer: dict) -> None:
        """Tell the session what the coach showed, so the hand history can say "deviated".

        Call it with the lock held.
        """
        headline = answer.get("headline")
        if answer.get("status") != "ready" or not isinstance(headline, dict):
            return
        if not headline.get("verb") or headline.get("tone") == "wait":
            return                                          # nothing was advised
        try:
            self.session.record_advice(rev, headline["verb"], headline.get("follow"))
        except Exception:                                   # the answer still goes to the page
            if self.verbose:
                print_traceback()


def is_provisional(answer: dict) -> bool:
    """An answer made while charts it needs were still being worked out (see ``PROVISIONAL``)."""
    warnings = answer.get("warnings")
    return isinstance(warnings, list) and any(isinstance(w, dict) and w.get("code") == PROVISIONAL for w in warnings)


def print_traceback() -> None:
    if sys.stderr is not None:                              # the packaged program may have no console
        traceback.print_exc()


# ==========================================================================
# 3. Files of the page
# ==========================================================================

def find_static_file(root: str, url_path: str):
    """The file under ``root`` that a URL path names, or ``None``.

    Every part of the path must be the exact name of something that really is in the folder.
    A directory listing never contains "..", a drive letter or a name with a slash in it, so a
    path cannot climb out of ``root``; a folder is not a file, so nothing is ever listed.
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


def refuse_constant(name: str):
    """NaN and Infinity are not JSON, and no chip count is either of them."""
    raise ValueError(f"{name} is not a number the table can use")


class Handler(BaseHTTPRequestHandler):
    """One request, one answer, and the connection is closed (HTTP/1.0: on this computer that costs nothing)."""

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
        except Exception:
            print_traceback()               # a fault of the program: worth seeing even without --verbose
            try:
                self._send_error(500, "The program failed on this request.",
                                 "Reload the page. If it happens again, restart the program.")
            except (ConnectionError, TimeoutError):
                pass

    def _get(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/api/view":
            self._send_json(200, self.app.view())
        elif url.path == "/api/ping":
            self._send_json(200, self.app.ping(self.server.server_port))
        elif url.path == "/api/advice":
            self._send_json(200, self.app.advice(self._rev_asked(url.query)))
        elif url.path == "/api/intent":
            raise BadRequest(405, "A change is sent with POST.", 'POST {"op": "..."} to /api/intent.')
        elif url.path.startswith("/api/"):
            raise BadRequest(404, f"There is no {url.path}.",
                             "The addresses are /api/view, /api/intent, /api/advice and /api/ping.")
        else:
            self._send_file(url.path)

    def _post(self) -> None:
        if not self._origin_is_ours():
            return
        url = urlsplit(self.path)
        if url.path != "/api/intent":
            raise BadRequest(405 if url.path in ("/api/view", "/api/advice", "/api/ping") else 404,
                             f"Nothing can be sent to {url.path}.", "Changes go to /api/intent.")
        answer = self.app.intent(self._json_body())
        # made on a view that is no longer the table: 409, with the table as it is now
        stale = "error" in answer and answer["error"].get("code") == "stale"
        self._send_json(409 if stale else 200, answer)

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
            # Read what was sent before answering: a sender that is still writing when the
            # connection closes sees a broken connection, not the 413.
            left = min(length, MAX_DROPPED)
            while left > 0:
                piece = self.rfile.read(min(65536, left))
                if not piece:
                    break
                left -= len(piece)
            raise BadRequest(413, "The request is too big.", fix)
        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"), parse_constant=refuse_constant)
        except (ValueError, RecursionError):    # not UTF-8, not JSON, or brackets nested a thousand deep
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


# ==========================================================================
# 5. Starting and stopping
# ==========================================================================

class AlreadyRunning(OSError):
    """A copy of the program already serves this folder of tables.  ``address`` is its page."""

    def __init__(self, address: str):
        super().__init__(f"Poker Coach is already running at {address}")
        self.address = address


def same_folder(path: str) -> str:
    """A folder's name in the one spelling two programs can compare."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def running_copy(folder: str):
    """The page address of the copy of this program that serves ``folder``, or ``None``.

    The copy left ``app.lock`` there with its port.  It counts only when something answers
    ``/api/ping`` on that port as this program with this folder: a lock nobody answers for was
    left by a copy that was killed, and is taken over.
    """
    try:
        with open(os.path.join(folder, LOCK_NAME), encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None                                         # no lock, or not one of ours
    return copy_at(port, folder)


def copy_at(port: int, folder: str):
    """The page address when the program on this port is this program serving ``folder``, else ``None``."""
    import http.client

    if not 0 < port <= 65535:
        return None
    link = http.client.HTTPConnection("127.0.0.1", port, timeout=PING_SECONDS)     # never through a proxy
    try:
        link.request("GET", "/api/ping")
        answer = link.getresponse()
        told = json.loads(answer.read(65536).decode("utf-8"))
        if answer.status == 200 and told.get("app") == APP_NAME and told.get("folder") == same_folder(folder):
            return f"http://127.0.0.1:{port}/"
    except (OSError, ValueError, AttributeError, http.client.HTTPException):
        pass                                                # nothing listens there, or it is another program
    finally:
        link.close()
    return None


class TableServer(ThreadingHTTPServer):
    """The HTTP server: a thread per request, this computer only."""

    daemon_threads = True                   # Ctrl+C does not wait for a browser's idle connections
    # "Reuse address" lets the program restart at once on the same port.  On Windows it would
    # also let two programs listen on one port, so there it stays off.
    allow_reuse_address = os.name != "nt"
    request_queue_size = 32                 # a page asks for its dozen files at once; none of them should wait at the door

    def __init__(self, port: int, app: TableApp, verbose: bool = False):
        self.app = app
        self.verbose = verbose
        self.lock_path = None               # app.lock, once this server has written it
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

    def write_lock(self) -> None:
        """Say in the session folder that this copy serves it, and on which port."""
        folder = self.app.session.folder
        path = os.path.join(folder, LOCK_NAME)
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"app": APP_NAME, "pid": os.getpid(), "port": self.server_port, "started": time.time()}, fh)
            self.lock_path = path
        except OSError:                     # a folder that cannot be written: the first save will say so
            self.lock_path = None

    def server_close(self) -> None:
        """A clean stop: the port is given back and the lock taken away (when it is still this copy's)."""
        super().server_close()
        path, self.lock_path = self.lock_path, None
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                ours = json.load(fh).get("pid") == os.getpid()
            if ours:
                os.remove(path)
        except (OSError, ValueError, AttributeError):
            pass


def start_server(port: int = DEFAULT_PORT, folder: str | None = None, verbose: bool = False,
                 static: str | None = None, coach=None) -> TableServer:
    """Open the server on ``port``, or on the next free port after it (0: any free port).

    It is listening when this returns; ``serve_forever()`` starts the answering.  When a copy
    of the program already serves the folder, nothing is started or touched: ``AlreadyRunning``
    carries that copy's address.
    """
    if not 0 <= port <= 65535:
        raise ValueError(f"the port must be between 0 and 65535, not {port}")
    from .model import default_folder

    # Before a file of the folder is read or set aside: is a copy at work on it?  The lock says
    # where; the port asked for is tried too (a copy that could not write its lock).
    tables = folder or default_folder()
    other = running_copy(tables) or copy_at(port, tables)
    if other:
        raise AlreadyRunning(other)
    app = TableApp(folder, static, coach, verbose)
    last = port if port == 0 else min(port + PORT_TRIES - 1, 65535)
    problem = None
    for candidate in range(port, last + 1):
        try:
            server = TableServer(candidate, app, verbose)
        except OSError as err:
            problem = err                   # taken, or not allowed: try the next one
            continue
        server.write_lock()
        return server
    raise OSError(f"no free port from {port} to {last} ({problem})")


def main(port: int = DEFAULT_PORT, open_browser: bool = True, verbose: bool = False,
         folder: str | None = None) -> int:
    """Start the table app and serve it until Ctrl+C.  Started a second time, it opens the running copy's page."""
    try:
        server = start_server(port, folder, verbose)
    except AlreadyRunning as running:
        print(f"Poker Coach is already running at {running.address}", flush=True)
        if open_browser:
            webbrowser.open(running.address)
        return 0
    address = f"http://127.0.0.1:{server.server_port}/"
    moved = f"port {port} was taken; " if port and server.server_port != port else ""
    print(f"Menlo Coach is running at {address}  ({moved}Ctrl+C stops it)", flush=True)
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
