"""The table app's local server: the page's files, /api/view, /api/intent, /api/advice.
Run: python -m unittest tests.test_app_server

Every test starts a real server on a free port of 127.0.0.1, with its own temporary folder for
the session files, and talks to it over HTTP like the page does.  Most tests give the server a
stand-in coach, so they do not depend on the advice adapter; ``AHandFromDealToResult`` uses
whatever ``poker_coach/app/advice.py`` is there, and passes when it is missing too.
"""

import http.client
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from urllib.parse import quote

import poker_coach.app
from poker_coach import cli
from poker_coach.app import server
from poker_coach.app.model import Session


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def stand_in_coach(session):
    """A coach for the tests: FOLD whenever it is hero's turn, and it says which table it was shown."""
    view = session.view()
    hand = view["hand"]
    if not hand or hand["needs"] != "action" or not hand["target_is_hero"]:
        return {"status": "none", "spot": "Nothing to advise."}
    return {"status": "ready", "spot": f"seen at revision {view['rev']}",
            "headline": {"verb": "FOLD", "tone": "fold", "follow": {"kind": "fold"}}}


def saved_files(folder) -> list:
    """The session files in a folder (beside them: the .bak copies and the lock of the running program)."""
    return sorted(name for name in os.listdir(folder) if name.endswith(".json"))


class ServerCase(unittest.TestCase):
    """A running server and the three calls the page makes."""

    coach = staticmethod(stand_in_coach)    # None: the real advice adapter
    static = None                           # None: the real page in poker_coach/app/static/
    verbose = False

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="menlo-app-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.server = None
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        self.server = server.start_server(0, folder=self.folder, verbose=self.verbose,
                                          static=self.static, coach=self.coach)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(5)
            self.server = None

    def restart(self):
        self.stop()
        self.start()

    def request(self, method, path, body=None, headers=None):
        """One request -> (status, headers, body).  The path goes out exactly as written here."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            answer = conn.getresponse()
            return answer.status, {name.lower(): value for name, value in answer.getheaders()}, answer.read()
        finally:
            conn.close()

    def get_json(self, path, status=200):
        got, headers, body = self.request("GET", path)
        self.assertEqual(got, status, body)
        self.assertEqual(headers["content-type"], "application/json")
        return json.loads(body)

    def view(self):
        return self.get_json("/api/view")

    def advice(self, rev):
        return self.get_json(f"/api/advice?rev={rev}")

    def post(self, intent, headers=None):
        """POST one intent -> the whole answer: {"view": ...} or {"error": ..., "view": ...}."""
        got, _, body = self.request("POST", "/api/intent", json.dumps(intent).encode(),
                                    {"Content-Type": "application/json", **(headers or {})})
        self.assertEqual(got, 200, body)
        return json.loads(body)

    def do(self, op, **args):
        """An intent that must be accepted -> the new view."""
        answer = self.post({"op": op, **args})
        self.assertNotIn("error", answer)
        return answer["view"]


# --------------------------------------------------------------------------
# The page and its files
# --------------------------------------------------------------------------

class ThePage(ServerCase):
    def test_the_page_or_a_clear_message(self):
        status, headers, body = self.request("GET", "/")
        if os.path.exists(os.path.join(server.STATIC_FOLDER, "index.html")):
            self.assertEqual(status, 200)
            self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
            self.assertIn(b"<html", body.lower())
        else:                                           # the page is not written yet: say so, and where it belongs
            self.assertEqual(status, 404)
            self.assertIn(b"index.html", body)
            self.assertIn(b"/api/view answers", body)

    def test_the_server_works_without_the_page(self):
        self.stop()
        self.static = os.path.join(self.folder, "no-such-folder")
        self.start()
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 404)
        self.assertEqual(headers["content-type"], "text/plain; charset=utf-8")
        self.assertIn(b"The page is missing", body)
        self.assertIn(b"index.html", body)
        self.assertEqual(self.view()["mode"], "tournament")


class StaticFiles(ServerCase):
    FILES = {"index.html": "text/html; charset=utf-8", "app.css": "text/css; charset=utf-8",
             "app.js": "text/javascript; charset=utf-8", "data.json": "application/json",
             "fonts/inter.woff2": "font/woff2", "fonts/licence.txt": "text/plain; charset=utf-8",
             "mark.svg": "image/svg+xml", "shot.png": "image/png"}

    def setUp(self):
        # A page folder of our own, with a file beside it that must never be served.
        self.root = tempfile.mkdtemp(prefix="menlo-static-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.static = os.path.join(self.root, "static")
        os.makedirs(os.path.join(self.static, "fonts"))
        for name in self.FILES:
            self.write(os.path.join(self.static, name), "content of " + name)
        self.write(os.path.join(self.static, "run.exe"), "not a file of the page")
        self.write(os.path.join(self.root, "secret.txt"), "outside the page folder")
        super().setUp()

    @staticmethod
    def write(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_content_types(self):
        for name, content_type in self.FILES.items():
            status, headers, body = self.request("GET", "/" + name)
            self.assertEqual((status, headers["content-type"], body.decode()),
                             (200, content_type, "content of " + name), name)
            self.assertEqual(headers["content-length"], str(len(body)))
            self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_the_root_is_the_page(self):
        for path in ("/", "/index.html", "/?fixture=one", "/index.html?x=1#top"):
            status, _, body = self.request("GET", path)
            self.assertEqual((status, body), (200, b"content of index.html"), path)

    def test_head_sends_no_body(self):
        status, headers, body = self.request("HEAD", "/app.css")
        self.assertEqual((status, headers["content-length"], body), (200, str(len("content of app.css")), b""))

    def test_no_directory_listing(self):
        for path in ("/fonts", "/fonts/", "/fonts/.", "/."):
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"inter.woff2", body)

    def test_only_known_kinds_of_file(self):
        for path in ("/run.exe", "/missing.js", "/fonts/missing.woff2", "/INDEX.HTML"):
            status, headers, _ = self.request("GET", path)
            self.assertEqual((status, headers["content-type"]), (404, "text/plain; charset=utf-8"), path)

    def test_no_way_out_of_the_folder(self):
        outside = os.path.abspath(os.path.join(self.root, "secret.txt"))
        paths = ["/../../etc/passwd", "/../../../../../../../../etc/passwd", "/..%2f..%2fetc%2fpasswd",
                 "/%2e%2e/%2e%2e/etc/passwd", "//etc/passwd", "/fonts/../../secret.txt", "/../secret.txt",
                 "/..%2fsecret.txt", "/..\\secret.txt", "/..%5csecret.txt", "/fonts/..%5c..%5csecret.txt",
                 "/fonts\\..\\..\\secret.txt", "/" + quote(outside, safe="/"), "/" + quote(outside, safe=""),
                 "/fonts/../index.html", "/./index.html/", "/index.html%00.png", "/C:/Windows/win.ini"]
        for path in paths:
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"outside the page folder", body, path)
            self.assertNotIn(b"root:", body, path)

    def test_find_static_file(self):
        find = server.find_static_file
        self.assertEqual(find(self.static, "/"), os.path.join(self.static, "index.html"))
        self.assertEqual(find(self.static, "/fonts/inter.woff2"), os.path.join(self.static, "fonts", "inter.woff2"))
        for path in ("/fonts", "/../secret.txt", "/..", "/fonts/../index.html", "/nothing/at/all", "/index.html/x"):
            self.assertIsNone(find(self.static, path), path)


# --------------------------------------------------------------------------
# A hand through the three addresses
# --------------------------------------------------------------------------

class AHandFromDealToResult(ServerCase):
    coach = None                                        # the real advice adapter, or none when it is not written yet

    def check_advice(self, rev):
        """The coach's answer for the revision on screen: an answer, or "none" with the reason."""
        answer = self.advice(rev)
        self.assertEqual(answer["rev"], rev)
        self.assertIn(answer["status"], ("ready", "none"))
        if answer["status"] == "ready":
            self.assertIsInstance(answer["headline"], dict)
        return answer

    def test_a_hand(self):
        # Six players with 10,000, blinds 100/200 with a 25 ante, hero on the button.
        # Seat 4 (LJ) raises, hero calls, they check to the river and hero wins.
        view = self.view()
        self.assertEqual((view["mode"], view["hand"], view["first_run"]), ("tournament", None, True))
        rev = view["rev"]

        view = self.do("new_session", size=6, start_stack=10000, button=1, level="100/200")
        self.assertEqual((view["rev"], view["first_run"], view["table"]["size"]), (rev + 1, False, 6))
        self.check_advice(view["rev"])                  # between hands: asking is allowed
        self.assertEqual(self.advice(rev), {"status": "stale"})

        view = self.do("deal", hero_cards="AhKd")
        hand = view["hand"]
        self.assertEqual((hand["no"], hand["phase"], hand["needs"], hand["target"], hand["hero_cards"]),
                         (1, "preflop", "action", 1, ["Ah", "Kd"]))
        self.assertEqual((hand["pot"], hand["to_call"]), (450, 200))          # blinds 300 and six antes of 25
        self.assertEqual(self.view()["hand"], hand)     # GET /api/view shows what the intent answered
        self.check_advice(view["rev"])

        view = self.do("act", seat=4, kind="raise", amount=500)
        self.assertEqual((view["hand"]["to_call"], view["hand"]["target_is_hero"]), (500, True))
        self.check_advice(view["rev"])

        view = self.do("act", kind="call")              # hero; the two seats before him are folded for him
        self.assertEqual([item["text"] for item in view["hand"]["line"]],
                         ["AhKd", "LJ raise 2.5bb", "HJ fold", "CO fold", "You call"])
        view = self.do("close_round")                   # the blinds fold
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"], view["hand"]["pot"]), ("flop", "board", 1450))

        view = self.do("set_cards", board="Ks7d2c")
        self.assertEqual((view["hand"]["board"], view["hand"]["needs"]), (["Ks", "7d", "2c"], "action"))
        self.do("act", seat=4, kind="check")
        self.check_advice(self.view()["rev"])           # after the flop, checked to hero
        self.do("act", kind="check")
        for card in ("9h", "3s"):
            self.do("set_cards", board=card)
            self.do("act", seat=4, kind="check")
            view = self.do("act", kind="check")
        self.assertEqual((view["hand"]["phase"], view["hand"]["needs"]), ("showdown", "result"))

        before = view["rev"]
        view = self.do("award", hero="won")
        self.assertEqual((view["rev"], view["hand"]["needs"], view["hand"]["result"]["text"]),
                         (before + 1, "next", "You (BTN) win 1,450"))
        stacks = {seat["seat"]: seat["stack"] for seat in view["table"]["seats"]}
        self.assertEqual(stacks, {1: 10925, 2: 9875, 3: 9775, 4: 9475, 5: 9975, 6: 9975})
        self.assertEqual(sum(stacks.values()), 60000)
        self.assertEqual(view["table"]["button"], 2)    # the next hand is dealt one seat on
        entry = view["history"][0]                      # what the coach said in it is the adapter's business
        self.assertEqual((entry["no"], entry["cards"], entry["pos"], entry["net"]), (1, "AhKd", "BTN", 925))
        self.check_advice(view["rev"])                  # the hand is settled

        final = self.view()
        self.assertEqual((final["rev"], final["hand"]["result"], final["history"]),
                         (view["rev"], view["hand"]["result"], view["history"]))


class WhatTheCoachSaidGoesIntoTheHistory(ServerCase):
    def test_deviated(self):
        self.do("new_session", size=3, start_stack=5000, button=1, level="50/100")
        view = self.do("deal", hero_cards="7c2d")
        self.assertEqual(self.advice(view["rev"])["headline"]["verb"], "FOLD")
        self.do("act", kind="raise", amount=300)        # the coach said fold; hero raises and takes the blinds
        view = self.do("close_round")
        entry = view["history"][0]
        self.assertEqual((entry["advice"], entry["did"], entry["deviated"]), ("FOLD", "raise", True))

    def test_advice_that_was_never_asked_for_is_not_invented(self):
        self.do("new_session", size=3, start_stack=5000, button=1, level="50/100")
        self.do("deal", hero_cards="7c2d")
        self.do("act", kind="raise", amount=300)
        entry = self.do("close_round")["history"][0]
        self.assertEqual((entry["advice"], entry["deviated"]), ("", False))


# --------------------------------------------------------------------------
# Changes that are refused
# --------------------------------------------------------------------------

class Refusals(ServerCase):
    def test_a_refused_intent_says_why_and_changes_nothing(self):
        view = self.do("new_session", size=6)
        rev = view["rev"]
        answer = self.post({"op": "act", "kind": "fold"})           # no hand is being played
        self.assertEqual(answer["error"], {"message": "No hand is being played.", "fix": "Deal a new hand first (N)."})
        self.assertEqual(answer["view"]["rev"], rev)
        self.assertEqual(self.view(), {**view, "toast": None})

        for intent in ({"op": "no_such_operation"}, {"op": "set_stack", "seat": 99, "text": "5000"},
                       {"no": "op"}, ["deal"], "deal", 7, None):
            answer = self.post(intent)
            self.assertTrue(answer["error"]["message"], intent)
            self.assertIn("fix", answer["error"])
            self.assertEqual(answer["view"]["rev"], rev, intent)
        self.assertEqual(self.view()["rev"], rev)

    def test_a_duplicate_card_is_refused_and_the_hand_goes_on(self):
        self.do("new_session", size=2, start_stack=5000, button=1, level="50/100")
        self.do("deal", hero_cards="AhKd")
        self.do("act", kind="call")
        view = self.do("act", seat=2, kind="check")     # heads-up: the flop is next
        answer = self.post({"op": "set_cards", "board": "AhQs2c"})  # the ace of hearts is in hero's hand
        self.assertIn("error", answer)
        self.assertEqual((answer["view"]["rev"], answer["view"]["hand"]["board"]), (view["rev"], []))
        self.assertEqual(self.do("set_cards", board="AsQs2c")["rev"], view["rev"] + 1)

    def test_malformed_json_is_a_400(self):
        rev = self.view()["rev"]
        for body in (b"{not json", b"", b"{'op': 'deal'}", b"\xff\xfe\x00", b'{"op": "set_stack", "seat": 2, "text": NaN}',
                     b'{"op": "remaining", "value": Infinity}', b"[" * 100000):
            status, headers, answer = self.request("POST", "/api/intent", body, {"Content-Type": "application/json"})
            self.assertEqual((status, headers["content-type"]), (400, "application/json"), body[:30])
            error = json.loads(answer)["error"]
            self.assertEqual(error["message"], "The request is not JSON.")
            self.assertIn('{"op": "deal"}', error["fix"])
        self.assertEqual(self.view()["rev"], rev)

    def test_a_body_too_big(self):
        status, _, answer = self.request("POST", "/api/intent", b" " * (server.MAX_BODY + 1))
        self.assertEqual((status, json.loads(answer)["error"]["message"]), (413, "The request is too big."))

    def test_wrong_addresses_and_methods(self):
        for method, path, status in (("GET", "/api/intent", 405), ("POST", "/api/view", 405), ("POST", "/api/advice", 405),
                                     ("GET", "/api/nothing", 404), ("POST", "/api/nothing", 404), ("POST", "/", 404),
                                     ("GET", "/api/advice?rev=abc", 400), ("GET", "/api/advice?rev=1.5", 400)):
            got, headers, body = self.request(method, path, b"{}" if method == "POST" else None)
            self.assertEqual((got, headers["content-type"]), (status, "application/json"), (method, path))
            self.assertTrue(json.loads(body)["error"]["message"])
        status, _, _ = self.request("DELETE", "/api/view")
        self.assertEqual(status, 501)

    def test_a_fault_in_the_program_puts_the_saved_table_back(self):
        view = self.do("new_session", size=6, button=3)
        app = self.server.app

        def half_a_change(intent):
            app.session.data["table"]["button"] = 5     # a change that breaks off half-way
            raise ZeroDivisionError("division by zero")

        with mock.patch.object(app.session, "apply", half_a_change), redirect_stderr(io.StringIO()) as shown:
            answer = self.post({"op": "level_up"})
        self.assertEqual(answer["error"]["message"], "The program failed on that change.")     # no Python in it
        self.assertIn("Nothing was changed", answer["error"]["fix"])
        self.assertIn("ZeroDivisionError", shown.getvalue())        # a fault is worth a traceback
        self.assertEqual((answer["view"]["rev"], answer["view"]["table"]["button"]), (view["rev"], 3))
        self.assertEqual(self.do("level_up")["rev"], view["rev"] + 1)   # and the table goes on working
        self.assertEqual(self.view()["table"]["button"], 3)


# --------------------------------------------------------------------------
# Who may ask
# --------------------------------------------------------------------------

class WhoMayAsk(ServerCase):
    def test_a_foreign_host_is_refused(self):
        rev = self.do("new_session", size=6)["rev"]
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1.evil.example:{self.port}",
                     "127.0.0.1", "localhost", f"127.0.0.1:{self.port + 1}", f"[::1]:{self.port}", ""):
            for method, path, body in (("GET", "/api/view", None), ("GET", "/", None), ("GET", "/api/advice", None),
                                       ("POST", "/api/intent", b'{"op": "level_up"}')):
                status, _, answer = self.request(method, path, body, {"Host": host})
                self.assertEqual(status, 403, (host, path))
                self.assertIn(b"Refused", answer)
                self.assertNotIn(b'"rev"', answer)
        self.assertEqual(self.view()["rev"], rev)                   # none of the POSTs changed anything

    def test_this_computer_under_both_names(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LocalHost:{self.port}"):
            status, _, body = self.request("GET", "/api/view", None, {"Host": host})
            self.assertEqual(status, 200, host)
            self.assertIn("rev", json.loads(body))

    def test_a_change_sent_by_another_site_is_refused(self):
        rev = self.view()["rev"]
        for origin in ("http://evil.example", f"http://evil.example:{self.port}", "null",
                       f"https://127.0.0.1:{self.port}", "http://127.0.0.1"):
            status, _, answer = self.request("POST", "/api/intent", b'{"op": "level_up"}', {"Origin": origin})
            self.assertEqual(status, 403, origin)
            self.assertIn("another site", json.loads(answer)["error"]["message"])
        self.assertEqual(self.view()["rev"], rev)
        for origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
            rev += 1
            self.assertEqual(self.post({"op": "level_up"}, {"Origin": origin})["view"]["rev"], rev)

    def test_it_listens_on_this_computer_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_the_page_may_ask_nobody_else(self):
        for path in ("/", "/api/view"):
            _, headers, _ = self.request("GET", path)
            self.assertIn("default-src 'self'", headers["content-security-policy"])
            self.assertNotIn("http", headers["content-security-policy"])


# --------------------------------------------------------------------------
# The coach's answer
# --------------------------------------------------------------------------

class Advice(ServerCase):
    def setUp(self):
        self.asked = []                                 # the revisions the coach was asked about
        self.coach = self.counting_coach
        super().setUp()

    def counting_coach(self, session):
        self.asked.append(session.rev)
        return stand_in_coach(session)

    def deal(self):
        self.do("new_session", size=3, start_stack=5000, button=1, level="50/100")
        return self.do("deal", hero_cards="AhKd")["rev"]

    def test_an_old_revision_is_stale(self):
        rev = self.deal()
        self.assertEqual((self.advice(rev)["status"], self.advice(rev)["rev"]), ("ready", rev))
        self.do("set_config", unit="bb")                # any accepted change makes a new revision
        self.assertEqual(self.advice(rev), {"status": "stale"})
        self.assertEqual(self.advice(rev - 1), {"status": "stale"})
        self.assertEqual(self.advice(rev + 5), {"status": "stale"})     # a revision that does not exist yet
        self.assertEqual(self.advice(rev + 1)["rev"], rev + 1)
        self.assertEqual(self.asked, [rev, rev + 1])    # nothing was worked out for the stale ones

    def test_without_a_revision_the_table_as_it_is_now(self):
        rev = self.deal()
        answer = self.get_json("/api/advice")
        self.assertEqual((answer["rev"], answer["status"]), (rev, "ready"))

    def test_an_answer_is_kept_until_the_table_changes(self):
        rev = self.deal()
        first = self.advice(rev)
        self.assertEqual([self.advice(rev) for _ in range(3)], [first] * 3)
        self.assertEqual(self.asked, [rev])
        self.post({"op": "act", "kind": "fly"})         # a refused change is no change
        self.assertEqual(self.advice(rev), first)
        self.assertEqual(self.asked, [rev])
        self.do("undo")
        self.advice(rev + 1)
        self.assertEqual(self.asked, [rev, rev + 1])

    def test_the_coach_reads_a_copy(self):
        seen = []

        def coach(session):
            seen.append(session)
            session.data["table"]["button"] = 3         # whatever the coach does to its copy stays there
            session.do("level_up")
            return stand_in_coach(session)

        self.server.app.coach = coach
        rev = self.deal()
        level = self.view()["strip"]["level"]
        self.assertEqual(self.advice(rev)["rev"], rev)
        self.assertIsNot(seen[0], self.server.app.session)
        view = self.view()
        self.assertEqual((view["rev"], view["table"]["button"], view["strip"]["level"]), (rev, 1, level))
        self.assertEqual(Session(self.folder).view()["rev"], rev)       # and nothing of it was saved

    def test_the_table_does_not_wait_for_the_coach(self):
        thinking, may_finish = threading.Event(), threading.Event()
        shown = {}

        def slow_coach(session):
            thinking.set()
            may_finish.wait(20)
            shown["rev"] = session.view()["rev"]        # the coach still sees the table it was given
            return stand_in_coach(session)

        self.server.app.coach = slow_coach
        rev = self.deal()
        answers = []
        asking = threading.Thread(target=lambda: answers.append(self.advice(rev)), daemon=True)
        asking.start()
        self.assertTrue(thinking.wait(10))
        try:
            # The engine is busy.  Everything else answers at once.
            self.assertEqual(self.view()["rev"], rev)
            self.assertEqual(self.advice(rev - 1), {"status": "stale"})
            view = self.do("act", kind="raise", amount=250)
            self.assertEqual(view["rev"], rev + 1)
            self.assertFalse(answers)                   # the coach has not answered yet
        finally:
            may_finish.set()
        asking.join(10)
        self.assertEqual(answers, [{"status": "stale"}])    # its answer was for a table that is gone
        self.assertEqual(shown["rev"], rev)
        self.assertEqual(self.view()["hand"]["line"][-1]["text"], view["hand"]["line"][-1]["text"])

    def test_two_requests_for_one_revision_are_one_question(self):
        thinking, may_finish = threading.Event(), threading.Event()

        def slow_coach(session):
            self.asked.append(session.rev)
            thinking.set()
            may_finish.wait(20)
            return stand_in_coach(session)

        self.server.app.coach = slow_coach
        rev = self.deal()
        answers = []
        threads = [threading.Thread(target=lambda: answers.append(self.advice(rev)), daemon=True) for _ in range(3)]
        for thread in threads:
            thread.start()
        self.assertTrue(thinking.wait(10))
        may_finish.set()
        for thread in threads:
            thread.join(10)
        self.assertEqual([answer["rev"] for answer in answers], [rev] * 3)
        self.assertEqual(self.asked, [rev])

    # ---- D10: an answer still being worked out when the table changes ----------------------------

    def held_coach(self):
        """A coach that answers a revision only when the test lets it -> (thinking, release): events by revision."""
        thinking, release = {}, {}
        guard = threading.Lock()

        def events(rev):
            with guard:
                return thinking.setdefault(rev, threading.Event()), release.setdefault(rev, threading.Event())

        def coach(session):
            self.asked.append(session.rev)
            started, go = events(session.rev)
            started.set()
            go.wait(20)
            return stand_in_coach(session)

        self.server.app.coach = coach
        return (lambda rev: events(rev)[0]), (lambda rev: events(rev)[1])

    def ask_in_a_thread(self, rev, answers):
        thread = threading.Thread(target=lambda: answers.__setitem__(rev, self.advice(rev)), daemon=True)
        thread.start()
        return thread

    def test_d10_the_answer_for_the_new_table_does_not_wait_for_the_stale_one(self):
        thinking, release = self.held_coach()
        rev = self.deal()
        answers = {}
        old = self.ask_in_a_thread(rev, answers)
        self.assertTrue(thinking(rev).wait(10))             # the answer for this table is being worked out ...
        self.assertEqual(self.do("set_config", unit="bb")["rev"], rev + 1)     # ... and the table changes
        release(rev + 1).set()                              # (the new table's answer takes no time)
        try:
            new = self.ask_in_a_thread(rev + 1, answers)
            new.join(10)
            # the new table has its answer while the old one is still being worked out
            self.assertEqual((answers.get(rev + 1) or {}).get("rev"), rev + 1)
            self.assertNotIn(rev, answers)
            self.assertEqual(self.advice(rev), {"status": "stale"})        # asked again for the old table: sent away at once
        finally:
            release(rev).set()
        old.join(10)
        self.assertEqual(answers[rev], {"status": "stale"})                # the old answer never reaches the page
        self.assertEqual(self.advice(rev + 1), answers[rev + 1])           # and it did not replace the kept one
        self.assertEqual(self.asked, [rev, rev + 1])

    def test_d10_no_work_is_done_or_queued_for_a_table_that_is_gone(self):
        thinking, release = self.held_coach()
        rev = self.deal()
        answers, threads = {}, {}
        try:
            threads[rev] = self.ask_in_a_thread(rev, answers)
            self.assertTrue(thinking(rev).wait(10))
            self.do("set_config", unit="bb")                                # rev + 1
            threads[rev + 1] = self.ask_in_a_thread(rev + 1, answers)
            self.assertTrue(thinking(rev + 1).wait(10))                     # two are being worked out: no more room
            self.do("set_config", unit="chips")                             # rev + 2
            threads[rev + 2] = self.ask_in_a_thread(rev + 2, answers)
            self.assertFalse(thinking(rev + 2).wait(0.3))                   # it waits for room
            self.do("set_config", unit="bb")                                # rev + 3: the one waiting is for a table that is gone
            threads[rev + 2].join(10)
            self.assertEqual(answers[rev + 2], {"status": "stale"})         # sent away at once, though both are still at work
            threads[rev + 3] = self.ask_in_a_thread(rev + 3, answers)
            self.assertFalse(thinking(rev + 3).wait(0.3))
            self.assertEqual(self.view()["rev"], rev + 3)                   # the table itself never waits
            release(rev).set()                                              # the oldest is done: room for the newest
            self.assertTrue(thinking(rev + 3).wait(10))
            release(rev + 3).set()
            threads[rev + 3].join(10)
            self.assertEqual(answers[rev + 3]["rev"], rev + 3)
        finally:
            for n in range(rev, rev + 4):
                release(n).set()
        for thread in threads.values():
            thread.join(10)
        self.assertEqual((answers[rev], answers[rev + 1]), ({"status": "stale"}, {"status": "stale"}))
        self.assertEqual(self.asked, [rev, rev + 1, rev + 3])               # nothing was worked out for rev + 2
        self.assertEqual(self.server.app._at_work, {})

    def test_d10_the_delay_for_trials_is_off_unless_somebody_sets_it(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(server.DELAY_VARIABLE, None)
            self.assertEqual(server.answer_delay(), 0.0)
            rev = self.deal()
            started = time.perf_counter()
            self.assertEqual(self.advice(rev)["rev"], rev)
            self.assertLess(time.perf_counter() - started, 0.25)
            os.environ[server.DELAY_VARIABLE] = "0.3"
            rev = self.do("set_config", unit="bb")["rev"]
            started = time.perf_counter()
            self.assertEqual(self.advice(rev)["rev"], rev)
            self.assertGreaterEqual(time.perf_counter() - started, 0.3)
            for text, seconds in (("", 0.0), ("soon", 0.0), ("-3", 0.0), ("1e9", 60.0)):
                os.environ[server.DELAY_VARIABLE] = text
                self.assertEqual(server.answer_delay(), seconds, text)
        # nothing the user starts sets it: not the starters, not the command line, not the packaged program
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("Start Poker Coach.bat", "Build exe.bat", os.path.join("poker_coach", "cli.py"),
                     os.path.join("tools", "coach_app.py"), os.path.join("tools", "build_exe.py")):
            with open(os.path.join(repo, name), encoding="utf-8", errors="replace") as fh:
                self.assertNotIn(server.DELAY_VARIABLE, fh.read(), name)

    def test_a_coach_that_fails_is_no_answer_and_the_table_goes_on(self):
        def nothing(session):
            return None

        def not_a_number(session):
            return {"status": "ready", "tiles": [{"value": float("nan")}]}

        def broken(session):
            raise KeyError("no such seat")

        rev = self.deal()
        for coach, text in ((broken, "KeyError: 'no such seat'"), (nothing, "TypeError"), (not_a_number, "ValueError")):
            self.server.app.coach = coach
            answer = self.advice(rev)
            self.assertEqual((answer["status"], answer["rev"]), ("none", rev), text)
            self.assertIn(text, answer["error"])                # the detail, for whoever looks into it
            self.assertNotIn("Error", answer["spot"])           # what the page says is plain words
            self.assertIn("cannot answer this spot", answer["spot"])
            rev = self.do("set_config", unit="bb")["rev"]       # a new revision: the coach is asked again
        self.assertEqual(self.view()["hand"]["needs"], "action")

    def test_without_the_adapter(self):
        self.server.app.coach = None                    # as the program runs: advice.py is looked for
        rev = self.deal()
        with mock.patch.object(server, "load_adapter", side_effect=ImportError("cannot import name 'advice'")):
            answer = self.advice(rev)
        self.assertEqual((answer["status"], answer["rev"]), ("none", rev))
        self.assertIn("ImportError: cannot import name 'advice'", answer["error"])
        self.assertEqual(self.do("act", kind="fold")["rev"], rev + 1)

    def test_the_adapter_is_found_by_its_function(self):
        def advise(session):
            return {"status": "ready", "headline": {"verb": "ALL-IN", "tone": "attack", "follow": None}}

        adapter = types.ModuleType("poker_coach.app.advice")
        adapter.advise = advise
        with mock.patch.dict(sys.modules, {"poker_coach.app.advice": adapter}), \
                mock.patch.object(poker_coach.app, "advice", adapter, create=True):
            self.assertIs(server.load_adapter(), advise)
            self.server.app.coach = None
            rev = self.deal()
            self.assertEqual(self.advice(rev)["headline"]["verb"], "ALL-IN")
            del adapter.advise
            with self.assertRaises(ImportError):
                server.load_adapter()

    def test_verbose_shows_the_coachs_error(self):
        def broken(session):
            raise KeyError("no such seat")

        self.server.app.coach = broken
        rev = self.deal()
        with redirect_stderr(io.StringIO()) as shown:
            self.advice(rev)
        self.assertEqual(shown.getvalue(), "")
        self.server.app.verbose = True
        rev = self.do("set_config", unit="bb")["rev"]
        with redirect_stderr(io.StringIO()) as shown:
            self.advice(rev)
        self.assertIn("KeyError: 'no such seat'", shown.getvalue())


# --------------------------------------------------------------------------
# What the page and the server agree on beyond the three addresses
# --------------------------------------------------------------------------

class ThePageAndTheServer(ServerCase):
    def side_pot_showdown(self):
        """Three players see a showdown: seat 3 is all-in for less, seats 1 and 2 bet on."""
        self.do("new_session", size=3, start_stack=5000, button=1, level="50/100")
        self.do("set_stack", seat=3, text="1000")
        self.do("deal", hero_cards="AhAd")
        for seat, kind in ((1, "raise"), (2, "call"), (3, "allin"), (1, "call"), (2, "call")):
            self.do("act", seat=seat, kind=kind)
        self.do("act", seat=2, kind="bet", amount=500)
        self.do("act", seat=1, kind="call")
        self.do("close_round")                          # the turn is checked through
        view = self.do("close_round")                   # and the river
        self.assertEqual((view["hand"]["needs"], len(view["hand"]["pots"])), ("result", 2))
        return view

    def test_a_side_pot_that_needs_a_winner_is_named_by_a_code(self):
        rev = self.side_pot_showdown()["rev"]
        answer = self.post({"op": "award", "ranking": [[3]]})       # the short stack wins: who wins the side pot?
        self.assertEqual(answer["error"]["code"], "side_pot")
        self.assertIn("side pot", answer["error"]["message"])
        self.assertEqual(answer["view"]["rev"], rev)
        answer = self.post({"op": "award", "ranking": [[9]]})       # another refusal: no code
        self.assertNotIn("code", answer["error"])
        view = self.do("award", ranking=[[3], [1]])                 # the page sends both tiers
        self.assertEqual(view["hand"]["needs"], "next")

    def test_a_number_too_big_gets_the_usual_refusal(self):
        view = self.do("new_session", size=6)
        answer = self.post({"op": "set_stack", "seat": 2, "text": "1e999"})
        self.assertIn("Cannot read '1e999' as an amount", answer["error"]["message"])
        self.assertNotIn("program failed", answer["error"]["message"])
        self.assertEqual(answer["view"]["rev"], view["rev"])

    def test_a_provisional_answer_is_not_kept(self):
        """While charts are still being worked out the coach answers with a warning; asking again gets the real answer."""
        asked = []

        def coach(session):
            asked.append(session.rev)
            answer = stand_in_coach(session)
            if len(asked) == 1:
                answer["warnings"] = [{"code": server.PROVISIONAL, "text": "The charts are still being worked out."}]
            return answer

        self.server.app.coach = coach
        self.do("new_session", size=6)
        rev = self.do("deal", hero_cards="AKs")["rev"]
        self.assertEqual(self.advice(rev)["warnings"][0]["code"], server.PROVISIONAL)
        self.assertNotIn("warnings", self.advice(rev))              # asked again: worked out again
        self.assertNotIn("warnings", self.advice(rev))              # and that answer is kept
        self.assertEqual(asked, [rev, rev])

    def test_the_all_in_plan_starts_on_its_charts_at_once(self):
        self.server.app.coach = None                                # the real adapter
        warmed = []
        adapter = types.SimpleNamespace(bubble_sheet=warmed.append, table_players=lambda players: 8 if players >= 8 else 6)
        with mock.patch.dict(sys.modules, {"poker_coach.app.advice": adapter}), \
                mock.patch.object(poker_coach.app, "advice", adapter, create=True):
            self.do("new_session", size=8)
            self.assertEqual(warmed, [])                            # the full plan needs none
            self.do("set_config", plan="allin")
            self.do("level_up")
            self.assertEqual(warmed, [8])                           # once for this table size
            self.do("clear_seat", seat=8)
            self.do("clear_seat", seat=7)
            self.assertEqual(warmed, [8, 6])                        # and once for the smaller table

    def test_every_command_of_the_key_map_has_its_function(self):
        """defaults.py names the commands, controller.js carries them out: the two lists must agree."""
        from poker_coach.app import defaults
        with open(os.path.join(server.STATIC_FOLDER, "controller.js"), encoding="utf-8") as fh:
            text = fh.read()
        table = text[text.index("const COMMANDS = {"):text.index("const SEAT_COMMANDS = {")]
        seat = text[text.index("const SEAT_COMMANDS = {"):text.index("function seatKey")]
        for group, block in (("table", table), ("seat", seat)):
            for _keys, command, _text in defaults.KEYS[group]:
                self.assertRegex(block, rf"\n    {command}(\(|: )", f"{group} command {command} is not in controller.js")

    def test_the_page_loads_its_three_scripts_in_order(self):
        status, _, body = self.request("GET", "/")
        page = body.decode("utf-8")
        self.assertEqual(status, 200)
        order = [page.index(f'<script src="{name}"></script>') for name in ("render.js", "controller.js", "app.js")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("http://", page.replace("http://www.w3.org/2000/svg", ""))    # nothing is asked of another site
        self.assertNotIn("https://", page)
        for name in ("render.js", "controller.js", "app.js", "app.css"):
            status, headers, _ = self.request("GET", "/" + name)
            self.assertEqual((status, headers["content-type"].split(";")[0]), (200, server.CONTENT_TYPES[os.path.splitext(name)[1]].split(";")[0]))


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------

class D7TheSavedExamplesOfThePage(unittest.TestCase):
    """D7: static/dev-fixtures.js (index.html?fixture=name) shows the page with answers written out by hand.

    The NO ADVICE example carried an older sentence with a Python error in it; the coach never
    sends one to the page.
    """

    def test_d7_the_no_advice_example_is_what_the_coach_really_answers(self):
        from poker_coach.app import advice
        with open(os.path.join(server.STATIC_FOLDER, "dev-fixtures.js"), encoding="utf-8") as fh:
            fixtures = fh.read()
        answer = advice.no_advice(advice.blank_answer(1), KeyError("UTG+3"))
        self.assertEqual(answer["reason"],
                         "The coach cannot read this spot. Play it from the sheet; the next one is advised as usual.")
        start = fixtures.index('add("no-advice"')
        example = fixtures[start:fixtures.index("}));", start)]
        self.assertIn(f'reason: {json.dumps(answer["reason"])},', example)
        self.assertIn(f'verb: {json.dumps(answer["headline"]["verb"])}', example)
        self.assertIn('follow: null', example)                      # nothing to follow, as in the coach's answer
        for word in ("KeyError", "ValueError", "TypeError", "Traceback", "engine stopped"):
            self.assertNotIn(word, fixtures)                        # no Python text in any example
        # the example of a program that does not answer says what the page says (controller.js NO_ANSWER)
        with open(os.path.join(server.STATIC_FOLDER, "controller.js"), encoding="utf-8") as fh:
            controller = fh.read()
        said = "Is it still running? Start it again (double-click Start Poker Coach) and reload this page."
        self.assertIn(said, controller)
        self.assertIn(said, fixtures)


class CloseT1AWindowShorterThanThePage(unittest.TestCase):
    """T1: in a window shorter than the page the answer stays at the top and the action bar at the foot.

    The page is a column of fixed heights, so "shorter than the page" is a number per width: 713px under
    1024 wide, 605 from 1024, 577 from 1280.  Under those the box around the table (index.html,
    #region-scroll) takes the room that is left and scrolls; before that the table takes a shorter form.
    What happens on screen is checked in the browser (short.js: a hand by keys and one by mouse at nine
    sizes; sizes.js: no overlap in the short windows).  Here: the pieces are there and their numbers agree.
    """

    def read(self, name: str) -> str:
        with open(os.path.join(server.STATIC_FOLDER, name), encoding="utf-8") as fh:
            return fh.read()

    def px(self, css: str, rule: str, what: str) -> int:
        """The first ``what:NNpx`` of the first rule that starts with ``rule``."""
        import re
        body = css[css.index(rule):]
        return int(re.search(re.escape(what) + r":(\d+)px", body[:body.index("}")]).group(1))

    def test_close_t1_the_table_has_a_box_that_can_scroll(self):
        page = self.read("index.html")
        parts = [page.index(f'id="region-{name}"') for name in ("header", "advice", "scroll", "table", "line", "actions")]
        self.assertEqual(parts, sorted(parts))                      # the order on the page is as it was
        box = page[page.index('<div id="region-scroll" class="scroll">'):page.index('<div id="region-line"')]
        self.assertIn('<section id="region-table" class="table"', box)
        self.assertEqual(box.count("</div>"), 1)                    # the table and nothing else is in it
        css = self.read("app.css")
        before_media = css[:css.index("@media", css.index(".scroll{display:contents}"))]
        self.assertTrue(before_media.rstrip().endswith(".scroll{display:contents}"))    # no box while the window is tall enough

    def test_close_t1_short_is_one_pixel_under_what_the_page_needs(self):
        css = self.read("app.css")
        root = css[css.index(":root{"):]
        token = lambda name, text=root: self.px(text, ":root{", name)
        # under 1024: header (bar, strip, its rule), slab, the line under it, table, hand line, action bar, five gaps, 8 under the bar
        bar, strip = self.px(css, ".bar{", "height"), self.px(css, ".strip{", "height")
        slab, whyline = self.px(css, ".slab{", "height"), self.px(css, ".whyline{", "min-height")
        # (the hand line is 44 high and gives 4 back above and below)
        line, caption, button = self.px(css, "\n.line{display", "height") - 8, self.px(css, ".actions .whose{", "height"), self.px(css, "\n.btn{", "min-height")
        narrow = bar + strip + 1 + slab + whyline + token("--table-h") + line + caption + 4 + button + 5 * token("--gap") + 8
        self.assertEqual(narrow, 713)
        self.assertIn(f"@media (max-width:1023px) and (max-height:{narrow - 1}px),", css)
        # from 1024: two columns, the header 52 + 52 + 1, table 360, gaps of 12: the action bar ends at 605
        wide = css[css.index("@media (min-width:1024px){"):]
        middle = 52 + strip + 1 + self.px(wide, ":root{", "--table-h") + line + caption + 4 + button + 3 * self.px(wide, ":root{", "--gap")
        self.assertEqual(middle, 605)
        self.assertIn(f"(min-width:1024px) and (max-width:1279px) and (max-height:{middle + 7}px),", css)
        # from 1280 (and under 630 high, where the table is the middle one): one header row of 64 + 1, gaps of 16: 577
        large = 64 + 1 + 360 + line + caption + 4 + button + 3 * 16
        self.assertEqual(large, 577)
        self.assertIn(f"(min-width:1280px) and (max-height:{large + 7}px){{", css)
        # the shorter forms end where their numbers say: one column 357 around the table, two columns 237, from 1024 253 and 225
        self.assertIn("--table-h:clamp(292px,calc(100vh - 357px),304px)", css)
        self.assertEqual(narrow - token("--table-h") - whyline - token("--gap"), 357)
        self.assertIn("--table-h:clamp(292px,calc(100vh - 237px),360px)", css)
        self.assertEqual(bar + strip + 1 + line + caption + 4 + button + 3 * token("--gap") + 8, 237)
        self.assertIn("--table-h:clamp(304px,calc(100vh - 253px),360px)", css)
        self.assertEqual(middle - 360 + 8, 253)
        self.assertIn("--table-h:clamp(304px,calc(100vh - 225px),360px)", css)
        self.assertEqual(large - 360 + 8, 225)

    def test_close_t1_the_box_rests_at_its_lower_end_and_the_reasons_stay_one_click_away(self):
        css, page = self.read("app.css"), self.read("render.js")
        short = css[css.index("/* ---------- 16. A window shorter than the page"):css.index("/* ---------- 17. Motion")]
        self.assertIn("flex-direction:column-reverse", short)       # laid out from its lower end: the user's cards
        self.assertIn(".app:not(.first)", short)                    # the first-run form scrolls as a page
        self.assertIn("position:fixed", short)                      # a menu on the table is not cut by the box
        self.assertIn(".whyline{display:none}", short)              # one column: the line under the slab gives its row ...
        self.assertIn(".slab .whybtn{display:inline-flex}", short)  # ... and its button stands in the slab
        self.assertIn(".slab .whybtn{display:none", css[:css.index(short)])
        self.assertIn('<button class="whybtn" data-fk="why"', page)
        self.assertIn('emit({ui: only({sheet: "why"})})}>Why${icon("chevron")}</button>', page)
        self.assertIn("    restTable(view, ui);\n", page)           # after every draw
        self.assertIn("box.scrollTop = 0;", page)
        # nothing of this hides the page from a poker client or reads the screen: it is layout only
        for word in ("setContentProtection", "getDisplayMedia", "captureStream"):
            self.assertNotIn(word, page)


class CloseT2AMoveButtonBelongsToItsPlayer(unittest.TestCase):
    """T2: a pointer click on a bar button is dropped for 400 ms after the bar changed the player it records for.

    Fold for the hijack and Fold for the cutoff stand at the same place with the same word.  The rule
    (render.js barClickTooEarly) knows a button by its name and its place; the name now carries the
    seat the button records for.  What happens on screen is checked in the browser (close.js, T2).
    """

    def test_close_t2_the_buttons_name_carries_the_seat_it_records_for(self):
        with open(os.path.join(server.STATIC_FOLDER, "render.js"), encoding="utf-8") as fh:
            page = fh.read()
        start = page.index("  function actBar(view, advice, ui) {")
        bar = page[start:page.index("\n  }\n", start)]
        moves = [line for line in bar.split("\n") if "barButton({label:" in line
                 and any(f'label: "{word}"' in line for word in ("Fold", "Check", "Call", "Bet", "Raise", "All-in"))]
        self.assertEqual(len(moves), 7)                             # fold, check, call, bet, raise, all-in; All-In or Fold's call
        for line in moves:
            self.assertIn("seat: seat,", line)
            self.assertIn("-\" + who", line)                        # (and hero's button is still not an opponent's)
        self.assertIn('const whom = opts.seat != null ? ` data-for="${opts.seat}"` : "";', page)
        start = page.index("  function barId(button) {")
        name = page[start:page.index("\n  }\n", start)]
        self.assertIn('(button.dataset.for ? "/seat " + button.dataset.for : "")', name)
        self.assertIn("const BAR_WAIT_MS = 400;", page)
        # a click by pointer only: Enter or Space on a focused button, and the keys, are not held back
        self.assertIn('const onBar = event.detail > 0 && element.tagName === "BUTTON" && !!element.closest("#region-actions");', page)


class CloseT5TheNamesOfAFinishedHandAfterAnUndo(unittest.TestCase):
    """T5 (UNDONAMES): a finished hand, a seat change and its undo.

    The pods of a finished hand keep that hand's seat names until the user moves the button or changes a
    seat; from then on they show the next hand's (render.js finishedHandNames).  An undo that brings the
    table back used to leave the next hand's names on the pods while the slab still said "You (UTG) win".
    The view of an undo carries toast.redo; with the table as it stood, the hand's own names come back.
    On screen: close.js, T5.  (AKEY, the other small one, was left: see the closing notes.)
    """

    def test_close_t5_an_undo_brings_the_hands_own_names_back(self):
        with open(os.path.join(server.STATIC_FOLDER, "render.js"), encoding="utf-8") as fh:
            page = fh.read()
        start = page.index("  function finishedHandNames(view) {")
        rule = page[start:page.index("\n  }\n", start)]
        self.assertIn("if (settledSeen.signature !== signature) settledSeen.moved = true;\n"
                      "    else if (view.toast && view.toast.redo) settledSeen.moved = false;", rule)
        # the model says so in the view of an undo, and only there
        tmp = tempfile.mkdtemp(prefix="menlo-close-t5-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        session = Session(folder=tmp)
        session.apply({"op": "new_session", "mode": "tournament", "size": 8, "start_stack": 20000, "level": "300/600/75", "button": 6})
        session.apply({"op": "deal", "hero_cards": "AhKh"})
        session.apply({"op": "act", "seat": 1, "kind": "raise", "amount": 1200})
        over = session.apply({"op": "close_round"})
        self.assertEqual((over["hand"]["needs"], over["hand"]["positions"]["1"], over["table"]["seats"][0]["pos"]), ("next", "UTG", "BB"))
        changed = session.apply({"op": "clear_seat", "seat": 3})
        self.assertFalse((changed["toast"] or {}).get("redo"))
        undone = session.apply({"op": "undo"})
        self.assertTrue(undone["toast"]["redo"])
        self.assertEqual((undone["hand"]["positions"], undone["table"]["button"]), (over["hand"]["positions"], over["table"]["button"]))
        self.assertEqual([seat["pos"] for seat in undone["table"]["seats"]], [seat["pos"] for seat in over["table"]["seats"]])


class GateThePageInSmallWindows(unittest.TestCase):
    """What the final gate found on the page and fixed.  Each is checked on screen in the browser (gate.js).

    G1  560 wide: a click on "Paid" in the strip opened nothing: the strip was too short for the field,
        and the part that gave way was the places paid themselves.  A value that is being typed stays.
    G2  The first-run form in a short window: what the program has to say there (a saved table that
        could not be read) was under the window's edge, and so was Start at 1024 x 476.
    G3  A scroll position of the table's box came back when the window was made small a second time:
        the box was put to rest after a draw only, not after a resize.
    G4  A click on the action bar inside the 400 ms was dropped without a trace: the button now looks held.
    G5  While the turn or the river is wanted, two toasts told the user to type the flop's three cards.
    G6  The settings said "[ and ] move the button by hand, also onto an empty seat": they step from
        player to player.
    """

    def read(self, name: str) -> str:
        with open(os.path.join(server.STATIC_FOLDER, name), encoding="utf-8") as fh:
            return fh.read()

    def body(self, text: str, start: str) -> str:
        """The function (or rule set) of the page that begins with ``start``, up to its closing line."""
        at = text.index(start)
        return text[at:text.index("\n  }\n", at)]

    def test_gate_g1_a_value_that_is_being_typed_stays_in_the_strip(self):
        page, css = self.read("render.js"), self.read("app.css")
        fit = self.body(page, "  function fitStrip() {")
        self.assertIn('const typed = strip.querySelector(".editing");', fit)
        self.assertIn('typed.closest(".stat.paid") ? "no-paid"', fit)       # its own turn to give way is passed over ...
        self.assertIn('["no-stage"].concat(GIVE_WAY.filter((name) => name !== own))', fit)     # ... and the pill leaves first
        self.assertIn('GIVE_WAY.concat("no-stage").forEach((name) => header.classList.remove(name));', fit)
        self.assertIn(",.header.no-stage .strip .stage{display:none}", css)
        # the field needs more room than the value it replaces: 84 against a button of 44 or more
        self.assertIn(".strip .in.short{width:84px}", css)

    def test_gate_g2_the_first_run_form_in_a_short_window(self):
        css = self.read("app.css")
        short = css[css.index("/* ---------- 16. A window shorter than the page"):css.index("/* ---------- 17. Motion")]
        self.assertIn("@media (max-height:640px){\n  .app.first .toasts{grid-row:2}\n}", short)       # over the form's title
        self.assertIn("@media (max-height:524px){\n  .first-run .stacked .hint{order:1}\n}", short)   # Start before the small print
        # in a window as tall as the form nothing changes: the toast keeps its row under the form
        before = css[:css.index(short)]
        self.assertIn(".app.first .toasts{grid-row:3}", before)
        self.assertIn(".stacked{display:flex;flex-direction:column;gap:10px}", before)    # (order works on a flex column)
        # the notice is the first view's toast, on the first-run form too
        page = self.read("render.js")
        self.assertIn("const toast = toastHtml(view || (said ? {toast: said} : null), ui);", page)

    def test_gate_g2_a_file_set_aside_is_said_on_the_first_run_form(self):
        tmp = tempfile.mkdtemp(prefix="pc-gate-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with open(os.path.join(tmp, "tournament.json"), "w", encoding="utf-8") as fh:
            fh.write("not json")
        view = Session(folder=tmp).view()
        self.assertTrue(view["first_run"])
        self.assertIn("could not be read and was set aside as tournament.json.unreadable-", view["toast"]["text"])
        self.assertIn("This is a new table", view["toast"]["text"])

    def test_gate_g3_the_tables_box_is_put_to_rest_after_a_resize_too(self):
        page = self.read("render.js")
        self.assertIn('window.addEventListener("resize", onResize);', page)
        self.assertNotIn('window.addEventListener("resize", fitStrip);', page)
        resize = self.body(page, "  function onResize() {")
        self.assertIn("fitStrip();", resize)
        self.assertIn("restTable(resting[0], resting[1]);", resize)
        self.assertIn("    restTable(view, ui);\n    resting = [view, ui];\n", page)       # the view and ui of the last draw
        rest = self.body(page, "  function restTable(view, ui) {")
        # a window as tall as the page forgets where the box rested, so the next short window starts at the user's cards
        self.assertIn('getComputedStyle(box).display === "contents") { restKey = ""; lifted = false; return; }', rest)
        self.assertIn("} else if (lifted || key !== restKey) {\n      box.scrollTop = 0;", rest)

    def test_gate_g4_a_bar_button_that_does_not_listen_yet_looks_held(self):
        page, css = self.read("render.js"), self.read("app.css")
        note = self.body(page, "  function noteBar() {")
        self.assertIn("const left = BAR_WAIT_MS - (now - next[id]);", note)
        self.assertIn('button.classList.toggle("held", left > 0 && button.hasAttribute("data-emit"));', note)
        self.assertIn("if (wait > 0) heldTimer = setTimeout(noteBar, wait + 1);", note)     # taken off when the last new button listens
        self.assertIn(".actions:hover .btn.held:not(:disabled){opacity:.45}", css)
        # the rule itself is as it was: 400 ms, pointer clicks only
        self.assertIn("const BAR_WAIT_MS = 400;", page)
        early = self.body(page, "  function barClickTooEarly(button) {")
        self.assertIn("return since == null || performance.now() - since < BAR_WAIT_MS;", early)
        self.assertIn("if (onBar && barClickTooEarly(element)) return;", page)

    def test_gate_g5_a_toast_names_the_cards_of_the_street_that_is_wanted(self):
        from poker_coach.app import model
        page = self.read("controller.js")
        self.assertIn('const STREET_KEYS = {flop: "K S 7 D 2 C", turn: "5 H", river: "9 C"};', page)
        self.assertEqual(model.BOARD_EXAMPLE, {"flop": "K S 7 D 2 C", "turn": "5 H", "river": "9 C"})     # the program's own refusals
        toasts = [line for line in page.split("\n") if "toast(" in line and "K S 7 D 2 C" in line]
        self.assertEqual(toasts, [])                                # no toast carries the flop's cards whatever the street
        self.assertIn('typeTheStreet(state.view, "Type them", "Type it") + ". Enter skips the board."', page)
        self.assertIn('typeTheStreet(state.view, "Type its cards first", "Type its card first") + "."', page)
        street = self.body(page, "  function typeTheStreet(view, three, one) {")
        self.assertIn('street === "turn" || street === "river" ? one : three', street)

    def test_gate_g6_the_bracket_keys_step_from_player_to_player(self):
        page = self.read("render.js")
        self.assertNotIn("also onto an empty seat", page)
        self.assertIn("[ and ] move the button by hand, from player to player. A seat's number, then D, puts it on that seat, an empty one too.", page)
        session = Session(save=False)
        session.apply({"op": "new_session", "mode": "tournament", "size": 8, "start_stack": 20000, "level": "300/600/75", "button": 1})
        session.apply({"op": "clear_seat", "seat": 3})
        buttons = [session.apply({"op": "button_step", "step": step})["table"]["button"] for step in (1, 1, -1, -1)]
        self.assertEqual(buttons, [2, 4, 2, 1])                     # the empty seat 3 is stepped over, both ways
        self.assertEqual(session.apply({"op": "set_button", "seat": 3})["table"]["button"], 3)     # a seat's number, then D


class Saving(ServerCase):
    def test_the_session_survives_a_restart(self):
        self.do("new_session", size=6, start_stack=10000, button=1, level="300/600/75")
        self.do("rename", seat=4, name="Hal")
        self.do("deal", hero_cards="AhKd")
        view = self.do("act", seat=4, kind="raise", amount="2.2bb")
        self.assertEqual(self.advice(view["rev"])["status"], "ready")
        before = self.view()
        self.assertEqual(saved_files(self.folder), ["app.json", "tournament.json"])

        self.restart()
        self.assertEqual(self.view(), before)
        self.assertEqual(self.advice(before["rev"])["rev"], before["rev"])      # worked out again for the same table
        view = self.do("undo")                                                  # the undo history came back too
        self.assertEqual(view["rev"], before["rev"] + 1)
        self.assertEqual(view["hand"]["line"][-1]["kind"], "cards")

    def test_each_mode_keeps_its_own_session(self):
        self.do("new_session", size=6, start_stack=10000)
        self.do("rename", seat=2, name="Tourney")
        self.do("deal", hero_cards="QsQh")
        view = self.do("set_mode", mode="spin")
        self.assertEqual((view["mode"], view["table"]["size"], view["hand"]), ("spin", 3, None))
        self.do("rename", seat=2, name="Spinner")
        self.do("set_mode", mode="aof")
        before = self.view()
        self.assertEqual(saved_files(self.folder), ["aof.json", "app.json", "spin.json", "tournament.json"])

        self.restart()
        self.assertEqual(self.view(), before)                                   # the mode on screen is remembered
        self.assertEqual(self.do("set_mode", mode="spin")["table"]["seats"][1]["name"], "Spinner")
        view = self.do("set_mode", mode="tournament")
        self.assertEqual((view["table"]["seats"][1]["name"], view["hand"]["hero_cards"]), ("Tourney", ["Qs", "Qh"]))

    def test_no_files_until_something_is_accepted(self):
        self.view()
        self.advice(self.view()["rev"])
        self.post({"op": "act", "kind": "fold"})        # refused
        self.assertEqual(saved_files(self.folder), [])


# --------------------------------------------------------------------------
# Starting, the log, the command
# --------------------------------------------------------------------------

class Starting(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="menlo-app-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_the_next_port_when_the_port_is_taken(self):
        taken = socket.socket()
        self.addCleanup(taken.close)
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        srv = server.start_server(port, folder=self.folder)
        self.addCleanup(srv.server_close)
        self.assertIn(srv.server_port, range(port + 1, port + server.PORT_TRIES))

    def test_no_free_port_is_said_plainly(self):
        with mock.patch.object(server, "TableServer", side_effect=OSError("address already in use")):
            with self.assertRaises(OSError) as caught:
                server.start_server(9000, folder=self.folder)
        self.assertIn("no free port from 9000 to 9019", str(caught.exception))
        for port in (-1, 70000):
            with self.assertRaises(ValueError):
                server.start_server(port, folder=self.folder)

    def run_main(self, **options):
        """Run ``server.main`` with Ctrl+C pressed as soon as it serves -> (exit code, what it printed, the server)."""
        started = []

        def serve_until_ctrl_c(srv, poll_interval=0.5):
            started.append(srv)
            raise KeyboardInterrupt

        with mock.patch.object(server.TableServer, "serve_forever", serve_until_ctrl_c), \
                redirect_stdout(io.StringIO()) as printed:
            code = server.main(folder=self.folder, **options)
        return code, printed.getvalue(), started[0]

    def test_main_prints_the_address_opens_the_browser_and_stops_cleanly(self):
        opened = threading.Event()
        addresses = []

        def open_browser(address):
            addresses.append(address)
            opened.set()

        with mock.patch.object(server.webbrowser, "open", open_browser):
            code, printed, srv = self.run_main(port=0)
            self.assertTrue(opened.wait(10))
        address = f"http://127.0.0.1:{srv.server_port}/"
        self.assertEqual(code, 0)
        self.assertEqual(printed.count("\n"), 1)                    # one line
        self.assertIn(address + " ", printed)
        self.assertIn("Ctrl+C", printed)
        self.assertEqual(addresses, [address])
        self.assertEqual(srv.socket.fileno(), -1)                   # the port is given back

    def test_main_without_the_browser(self):
        with mock.patch.object(server.webbrowser, "open", side_effect=AssertionError("the browser was opened")):
            code, printed, _ = self.run_main(port=0, open_browser=False)
        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:", printed)

    def test_main_says_when_the_port_moved(self):
        taken = socket.socket()
        self.addCleanup(taken.close)
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = taken.getsockname()[1]
        code, printed, srv = self.run_main(port=port, open_browser=False)
        self.assertNotEqual(srv.server_port, port)
        self.assertIn(f"port {port} was taken", printed)
        self.assertIn(f"http://127.0.0.1:{srv.server_port}/", printed)

    def test_d5_one_name_on_a_first_start_and_on_a_second(self):
        """The program calls itself Menlo Coach whenever it speaks: started once, started twice, refusing a stranger."""
        self.assertEqual(server.PROGRAM, "Menlo Coach")
        with open(os.path.join(server.STATIC_FOLDER, "index.html"), encoding="utf-8") as fh:
            self.assertIn(f"<title>{server.PROGRAM}</title>", fh.read())                # the page's title is the same name
        code, first, srv = self.run_main(port=0, open_browser=False)
        self.assertTrue(first.startswith("Menlo Coach is running at http://127.0.0.1:"), first)
        running = server.start_server(0, folder=self.folder)
        self.addCleanup(running.server_close)
        thread = threading.Thread(target=running.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(running.shutdown)
        with redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(server.main(port=0, open_browser=False, folder=self.folder), 0)
        second = printed.getvalue().strip()
        self.assertEqual(second, f"Menlo Coach is already running at http://127.0.0.1:{running.server_port}/")
        # a request addressed to another host is told whose address this is, by the same name
        link = http.client.HTTPConnection("127.0.0.1", running.server_port, timeout=20)
        self.addCleanup(link.close)
        link.request("GET", "/api/view", headers={"Host": "example.com"})
        answer = link.getresponse()
        self.assertEqual(answer.status, 403)
        self.assertIn("this is Menlo Coach on", answer.read().decode("utf-8"))
        with open(server.__file__, encoding="utf-8") as fh:
            self.assertNotIn("Poker Coach", fh.read())                                  # the old name is in no sentence of the server

    def test_the_command(self):
        parse = cli.build_parser().parse_args
        args = parse(["app"])
        self.assertEqual((args.port, args.no_browser, args.verbose), (8765, False, False))
        args = parse(["app", "--port", "9001", "--no-browser", "--verbose"])
        self.assertEqual((args.port, args.no_browser, args.verbose), (9001, True, True))
        self.assertIn("Table app:", cli.__doc__)
        with mock.patch.object(server, "main", return_value=0) as main:
            self.assertEqual(cli.main(["app", "--port", "9001", "--no-browser"]), 0)
        main.assert_called_once_with(port=9001, open_browser=False, verbose=False)
        with mock.patch.object(server, "main", return_value=0) as main:
            cli.main(["app"])
        main.assert_called_once_with(port=8765, open_browser=True, verbose=False)
        with mock.patch.object(server, "main", side_effect=OSError("no free port from 8765 to 8784")), \
                redirect_stderr(io.StringIO()) as shown:
            self.assertEqual(cli.main(["app"]), 2)
        self.assertIn("no free port", shown.getvalue())


class TheLog(ServerCase):
    def talk(self):
        self.do("new_session", size=6)
        self.view()
        self.advice(0)
        self.request("GET", "/")
        self.request("GET", "/nothing.js")
        self.request("GET", "/api/view", None, {"Host": "evil.example"})
        self.request("POST", "/api/intent", b"{not json")
        self.post({"op": "no_such_operation"})

    def test_quiet_by_default(self):
        with redirect_stderr(io.StringIO()) as shown, redirect_stdout(io.StringIO()) as printed:
            self.talk()
        self.assertEqual((shown.getvalue(), printed.getvalue()), ("", ""))

    def test_verbose_logs_every_request_to_stderr(self):
        self.stop()
        self.verbose = True
        self.start()
        with redirect_stderr(io.StringIO()) as shown, redirect_stdout(io.StringIO()) as printed:
            self.talk()
        lines = shown.getvalue().splitlines()
        self.assertEqual(printed.getvalue(), "")
        self.assertEqual(len(lines), 8)
        for part, line in zip(('"POST /api/intent HTTP/1.1" 200', '"GET /api/view HTTP/1.1" 200',
                               '"GET /api/advice?rev=0 HTTP/1.1" 200', '"GET / HTTP/1.1"', '"GET /nothing.js HTTP/1.1" 404',
                               '"GET /api/view HTTP/1.1" 403', '"POST /api/intent HTTP/1.1" 400',
                               '"POST /api/intent HTTP/1.1" 200'), lines):
            self.assertIn(part, line)
            self.assertRegex(line, r"^\d\d:\d\d:\d\d .* \d+ ms$")


# ==========================================================================
# The review round: one class per finding of the reports (ROB, the package report, the addendum)
# ==========================================================================

class Rob12StaleRevision(ServerCase):
    """ROB-12 (contract 9): an intent made on a view that is no longer the table changes nothing and answers 409."""

    def send(self, intent):
        status, _, body = self.request("POST", "/api/intent", json.dumps(intent).encode(),
                                       {"Content-Type": "application/json"})
        return status, json.loads(body)

    def test_rob_12_the_old_tab(self):
        self.do("new_session", size=6, start_stack=10000, level="100/200")
        old = self.view()["rev"]                                    # a tab left open between hands
        self.do("deal", hero_cards="AhAs")
        now = self.do("act", seat=6, kind="raise", amount=500)      # the current tab: hero to act with aces
        status, answer = self.send({"op": "deal", "rev": old})      # N pressed in the old tab
        self.assertEqual(status, 409)
        self.assertEqual(answer["error"]["code"], "stale")
        self.assertTrue(answer["error"]["message"] and answer["error"]["fix"])
        self.assertEqual(answer["view"], {**now, "toast": None})    # nothing changed, and the table as it is comes back
        self.assertEqual(self.view()["hand"]["hero_cards"], ["Ah", "As"])
        self.assertEqual(self.view()["history"], [])

    def test_rob_12_the_current_revision_and_no_revision(self):
        view = self.do("new_session", size=6)
        status, answer = self.send({"op": "rename", "seat": 2, "name": "Al", "rev": view["rev"]})
        self.assertEqual((status, answer["view"]["rev"]), (200, view["rev"] + 1))
        status, answer = self.send({"op": "rename", "seat": 2, "name": "Bo", "rev": view["rev"]})     # typed on the old rev
        name = answer["view"]["table"]["seats"][1]["name"]
        self.assertEqual((status, answer["error"]["code"], name), (409, "stale", "Al"))
        status, answer = self.send({"op": "rename", "seat": 2, "name": "Cy"})                         # no rev: as before
        self.assertEqual((status, answer["view"]["table"]["seats"][1]["name"]), (200, "Cy"))
        for rev in ("x", [1], True, -1, view["rev"] + 99):
            status, answer = self.send({"op": "rename", "seat": 2, "name": "Di", "rev": rev})
            self.assertEqual((status, answer["error"]["code"]), (409, "stale"), rev)
        status, answer = self.send({"op": "set_config", "unit": "bb", "rev": self.view()["rev"]})     # rev is not a setting
        self.assertEqual((status, answer["view"]["unit"]), (200, "bb"))
        status, answer = self.send({"op": "new_session", "mode": "spin", "rev": self.view()["rev"]})  # a mode change inside
        self.assertEqual((status, answer["view"]["mode"]), (200, "spin"))

    def test_rob_12_a_refusal_for_another_reason_is_still_a_200(self):
        view = self.do("new_session", size=6)
        status, answer = self.send({"op": "act", "kind": "fold", "rev": view["rev"]})
        self.assertEqual((status, "code" in answer["error"]), (200, False))


class Rob3OneCopyPerFolder(ServerCase):
    """ROB-3 and the package report (d): a second start on the same folder opens the running copy's page and ends."""

    def lock(self):
        with open(os.path.join(self.folder, server.LOCK_NAME), encoding="utf-8") as fh:
            return json.load(fh)

    def test_rob_3_a_running_copy_leaves_its_lock_and_answers_ping(self):
        lock = self.lock()
        self.assertEqual((lock["pid"], lock["port"], lock["app"]), (os.getpid(), self.port, server.APP_NAME))
        ping = self.get_json("/api/ping")
        self.assertEqual((ping["app"], ping["pid"], ping["port"]), (server.APP_NAME, os.getpid(), self.port))
        self.assertEqual(ping["folder"], server.same_folder(self.folder))
        self.assertEqual(server.running_copy(self.folder), f"http://127.0.0.1:{self.port}/")
        self.stop()                                                 # a clean stop takes the lock away
        self.assertNotIn(server.LOCK_NAME, os.listdir(self.folder))
        self.assertIsNone(server.running_copy(self.folder))

    def test_rob_3_a_second_start_steps_aside_and_touches_nothing(self):
        self.do("new_session", size=6)
        self.do("rename", seat=2, name="Bob")
        with open(os.path.join(self.folder, "tournament.json"), "w", encoding="utf-8") as fh:
            fh.write("{damaged")                                    # a second copy must not set this aside either
        before = sorted(os.listdir(self.folder))
        with self.assertRaises(server.AlreadyRunning) as caught:
            server.start_server(0, folder=self.folder)
        self.assertEqual(caught.exception.address, f"http://127.0.0.1:{self.port}/")
        self.assertIn("already running", str(caught.exception))
        self.assertEqual(sorted(os.listdir(self.folder)), before)
        self.assertEqual(self.do("rename", seat=3, name="Cy")["table"]["seats"][1]["name"], "Bob")    # the first copy goes on

    def test_package_d_main_prints_already_running_and_opens_the_page(self):
        address = f"http://127.0.0.1:{self.port}/"
        for open_browser in (True, False):
            with mock.patch.object(server.webbrowser, "open") as opened, \
                    mock.patch.object(server.TableServer, "serve_forever", side_effect=AssertionError("served twice")), \
                    redirect_stdout(io.StringIO()) as printed:
                code = server.main(port=self.port, open_browser=open_browser, folder=self.folder)
            self.assertEqual(code, 0)
            self.assertEqual(printed.getvalue().strip(), f"Menlo Coach is already running at {address}")
            self.assertEqual(opened.call_count, 1 if open_browser else 0)
            if open_browser:
                opened.assert_called_once_with(address)
        with mock.patch.object(server, "main", side_effect=server.main), \
                mock.patch.object(server.webbrowser, "open"), redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(cli.main(["app", "--folder", self.folder, "--port", "0"]), 0)        # the command line too
        self.assertIn("already running", printed.getvalue())

    def test_package_d_without_the_lock_the_port_asked_for_is_tried(self):
        os.remove(os.path.join(self.folder, server.LOCK_NAME))      # the lock was lost, the copy runs on
        self.assertIsNone(server.running_copy(self.folder))
        with self.assertRaises(server.AlreadyRunning) as caught:
            server.start_server(self.port, folder=self.folder)
        self.assertEqual(caught.exception.address, f"http://127.0.0.1:{self.port}/")
        other = tempfile.mkdtemp(prefix="menlo-other-")             # the same port asked for with other tables: next port
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        second = server.start_server(self.port, folder=other)
        self.addCleanup(second.server_close)
        self.assertNotEqual(second.server_port, self.port)

    def test_rob_3_another_folder_starts_a_copy_of_its_own(self):
        other = tempfile.mkdtemp(prefix="menlo-other-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        second = server.start_server(0, folder=other)
        self.addCleanup(second.server_close)
        self.assertNotEqual(second.server_port, self.port)
        self.assertIsNone(server.running_copy(tempfile.gettempdir()))

    def test_rob_3_a_lock_nobody_answers_for_is_taken_over(self):
        self.do("new_session", size=6)
        self.do("rename", seat=2, name="Bob")
        port = self.port
        self.server.lock_path = None                                # as if the program had been killed: the lock stays
        self.stop()
        self.assertEqual(self.lock()["port"], port)
        self.assertIsNone(server.running_copy(self.folder))
        self.start()                                                # the next start takes it over
        self.assertEqual((self.lock()["port"], self.lock()["pid"]), (self.port, os.getpid()))
        self.assertEqual(self.view()["table"]["seats"][1]["name"], "Bob")

    def test_rob_3_a_lock_that_points_at_something_else_is_stale(self):
        other_folder = tempfile.mkdtemp(prefix="menlo-other-")
        self.addCleanup(shutil.rmtree, other_folder, ignore_errors=True)
        silent = socket.socket()                                    # another program on the port in the lock
        self.addCleanup(silent.close)
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        for port in (self.port,                                     # a copy of the program, but with other tables
                     silent.getsockname()[1], 0, 70000, "x", None):
            with open(os.path.join(other_folder, server.LOCK_NAME), "w", encoding="utf-8") as fh:
                json.dump({"port": port, "pid": 1}, fh)
            with mock.patch.object(server, "PING_SECONDS", 0.2):
                self.assertIsNone(server.running_copy(other_folder), port)
        with open(os.path.join(other_folder, server.LOCK_NAME), "w", encoding="utf-8") as fh:
            fh.write("not json")
        self.assertIsNone(server.running_copy(other_folder))


class Rob14BodyTooBig(ServerCase):
    def test_rob_14_the_body_is_read_before_the_413(self):
        """A sender that writes its megabytes slowly still gets the answer, not a broken connection."""
        size = server.MAX_BODY * 2
        with socket.create_connection(("127.0.0.1", self.port), timeout=20) as sock:
            sock.sendall(f"POST /api/intent HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                         f"Content-Type: application/json\r\nContent-Length: {size}\r\n\r\n".encode())
            piece = b" " * 65536
            for _ in range(size // len(piece) + 1):                 # every piece is accepted: nothing breaks off
                sock.sendall(piece[:max(0, min(len(piece), size))])
                size -= len(piece)
                if size <= 0:
                    break
            answer = b""
            while True:
                got = sock.recv(65536)
                if not got:
                    break
                answer += got
        self.assertTrue(answer.startswith(b"HTTP/1.0 413") or answer.startswith(b"HTTP/1.1 413"), answer[:40])
        self.assertIn(b"The request is too big.", answer)
        self.assertEqual(self.view()["rev"], 0)                     # and the program goes on

    def test_rob_14_a_body_beyond_what_is_read_is_still_refused(self):
        with mock.patch.object(server, "MAX_DROPPED", 1_500_000):
            for _ in range(3):
                try:
                    status, _, _ = self.request("POST", "/api/intent", b" " * (server.MAX_BODY * 3))
                except (BrokenPipeError, ConnectionError):
                    status = 413                                    # the sender was still writing: that is the refusal
                self.assertEqual(status, 413)


class SavingThroughTheServer(ServerCase):
    """The package report (a): a change that could not be saved is made, and the page is told so; it is not a refusal."""

    def test_package_a_made_not_saved_yet_is_not_a_refusal(self):
        from poker_coach.app import model
        view = self.do("new_session", size=6)
        real = os.replace

        def held(src, dst):
            if str(src).endswith(".tmp"):
                raise PermissionError(13, "Access is denied")
            return real(src, dst)

        with mock.patch.object(model, "WRITE_WAIT", 0), mock.patch.object(model.os, "replace", held):
            answer = self.post({"op": "rename", "seat": 2, "name": "Bob"})
        self.assertNotIn("error", answer)
        self.assertEqual((answer["view"]["rev"], answer["view"]["table"]["seats"][1]["name"]), (view["rev"] + 1, "Bob"))
        self.assertIn("Made, not saved yet", answer["view"]["toast"]["text"])
        self.assertTrue(answer["view"]["unsaved"])
        self.assertTrue(self.view()["unsaved"])
        view = self.do("rename", seat=3, name="Cy")                 # the next change saves both
        self.assertEqual(view["unsaved"], "")
        self.restart()
        self.assertEqual([seat["name"] for seat in self.view()["table"]["seats"]][1:3], ["Bob", "Cy"])

    def test_rob_4_a_file_set_aside_is_told_in_the_first_view(self):
        self.do("new_session", size=6)
        self.stop()
        for name in os.listdir(self.folder):
            if name.endswith(".bak"):
                os.remove(os.path.join(self.folder, name))
        with open(os.path.join(self.folder, "tournament.json"), "w", encoding="utf-8") as fh:
            fh.write("{damaged")
        self.start()
        view = self.view()                                          # the page's first request
        self.assertTrue(view["first_run"])
        self.assertIn("tournament.json could not be read and was set aside as tournament.json.unreadable-",
                      view["toast"]["text"])

    def test_rob_4_a_held_file_stops_the_start_with_a_sentence(self):
        from poker_coach.app import model
        self.do("new_session", size=6)
        self.stop()
        real = open

        def held(path, *args, **kwargs):
            if str(path).endswith("tournament.json"):
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(path, *args, **kwargs)

        with mock.patch.object(model, "READ_WAIT", 0), mock.patch("builtins.open", held), \
                redirect_stderr(io.StringIO()) as shown:
            code = cli.main(["app", "--folder", self.folder, "--port", "0", "--no-browser"])
        self.assertEqual(code, 2)
        self.assertIn("Cannot read", shown.getvalue())
        self.assertIn("Close the program that holds the file and start again", shown.getvalue())
        self.assertEqual(saved_files(self.folder), ["app.json", "tournament.json"])    # nothing was renamed


class Rob9NoPythonInARefusal(ServerCase):
    verbose = True

    def test_rob_9_the_detail_goes_to_the_verbose_log(self):
        with redirect_stderr(io.StringIO()) as shown:
            self.do("new_session", size=6)
            deal = self.do("deal")
            answer2 = self.post({"op": "close_round", "callers": 7})
        for reply in (answer2,):
            text = reply["error"]["message"] + reply["error"]["fix"]
            self.assertIn("could not be read", text)
            for word in ("Error", "object", "iterable"):
                self.assertNotIn(word, text)
        self.assertIn("unreadable request: close_round: TypeError", shown.getvalue())
        self.assertEqual(answer2["view"]["rev"], deal["rev"])


class PackageCommandLine(unittest.TestCase):
    """The package report: the sync file is read as UTF-8, and a name the console cannot show does not stop a command."""

    def setUp(self):
        from poker_coach import state
        self.folder = tempfile.mkdtemp(prefix="menlo-cli-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        patch = mock.patch.object(state, "STATE_PATH", os.path.join(self.folder, "current.json"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_package_e_the_sync_file_is_read_as_utf_8(self):
        path = os.path.join(self.folder, "snapshot.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"blinds": [300, 600, 75], "button": 1, "hero": 2,
                       "seats": {"1": ["Jos\u00e9", 21000], "2": ["HERO", 12400]}}, fh, ensure_ascii=False)
        seen = {}
        real = open

        def watching(file, *args, **kwargs):
            if str(file) == path:
                seen["encoding"] = kwargs.get("encoding")
            return real(file, *args, **kwargs)

        with mock.patch("builtins.open", watching), redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(cli.main(["new", "--name", "t"]), 0)
            self.assertEqual(cli.main(["sync", "--file", path]), 0)
        self.assertEqual(seen["encoding"], "utf-8")                 # not the system's code page
        self.assertIn("Jos\u00e9", printed.getvalue())

    def test_package_e_a_name_outside_the_code_page_is_printed_with_an_escape(self):
        piped = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")   # Windows, output piped: the default would raise
        with mock.patch.object(sys, "stdout", piped):
            self.assertEqual(cli.main(["new", "--name", "t"]), 0)
            code = cli.main(["sync", json.dumps({"blinds": [300, 600, 75], "button": 1, "hero": 2,
                                                 "seats": {"1": ["\u0141ukasz", 21000], "2": ["HERO", 12400]}})])
            piped.flush()
            shown = piped.buffer.getvalue().decode("cp1252")
        self.assertEqual(code, 0)
        self.assertIn("\\u0141ukasz", shown)

    def test_rob_7_the_engine_needs_nothing_newer_than_python_3_9(self):
        path = os.path.join(os.path.dirname(os.path.abspath(cli.__file__)), "evaluator.py")
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn(".bit_count()", fh.read())
        from poker_coach.cards import parse_cards
        from poker_coach.evaluator import evaluate
        value = lambda cards: evaluate(parse_cards(cards))
        self.assertGreater(value("AhKhQhJhTh2c3d"), value("AhAdAsAc2h3d4c"))        # a straight flush beats quads
        self.assertGreater(value("Ah9h7h4h2hKcKd"), value("AhKdQsJcTh2c3d"))        # a flush beats a straight


class BehindAWebServer(ServerCase):
    """On a server of one's own: a web server on the same machine passes requests on (``--public-url``)."""

    public = "https://menlo.bet/coach"

    def start(self):
        self.server = server.start_server(0, folder=self.folder, verbose=self.verbose, static=self.static,
                                          coach=self.coach, public=self.public)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def test_the_address_is_read_once_and_a_wrong_one_is_refused_before_anything_starts(self):
        self.assertEqual(server.public_address("https://Menlo.bet/coach"), ("https://menlo.bet/coach/", "menlo.bet", "https://menlo.bet"))
        self.assertEqual(server.public_address("http://coach.example:8080/"), ("http://coach.example:8080/", "coach.example:8080", "http://coach.example:8080"))
        self.assertEqual(server.public_address(None), ("", "", ""))
        other = tempfile.mkdtemp(prefix="menlo-app-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        for wrong in ("menlo.bet/coach", "ftp://menlo.bet/", "https://", "https://user:pw@menlo.bet/", "https://menlo.bet/coach?x=1"):
            with self.assertRaises(ValueError, msg=wrong):
                server.start_server(0, folder=other, public=wrong)
        self.assertEqual(os.listdir(other), [])                     # nothing was started or written

    def test_requests_under_the_public_name_are_answered_and_others_still_refused(self):
        rev = self.do("new_session", size=6)["rev"]
        status, _, body = self.request("GET", "/api/view", None, {"Host": "menlo.bet"})
        self.assertEqual((status, json.loads(body)["rev"]), (200, rev))
        status, _, body = self.request("GET", "/", None, {"Host": "MENLO.BET"})
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", body)
        for host in ("evil.example", "menlo.bet.evil.example", "menlo.bet:8443", "coach.menlo.bet", ""):
            status, _, answer = self.request("GET", "/api/view", None, {"Host": host})
            self.assertEqual(status, 403, host)
            self.assertIn(b"Refused", answer)
        # this computer's own names still work: the web server may pass the request on under either
        status, _, _ = self.request("GET", "/api/view", None, {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)

    def test_a_change_from_the_public_page_is_taken_and_one_from_another_site_is_not(self):
        rev = self.view()["rev"]
        answer = self.post({"op": "level_up"}, {"Host": "menlo.bet", "Origin": "https://menlo.bet"})
        self.assertEqual(answer["view"]["rev"], rev + 1)
        for origin in ("http://menlo.bet", "https://menlo.bet.evil.example", "https://evil.example", "https://coach.menlo.bet", "null"):
            status, _, body = self.request("POST", "/api/intent", b'{"op": "level_up"}', {"Host": "menlo.bet", "Origin": origin})
            self.assertEqual(status, 403, origin)
            self.assertIn("another site", json.loads(body)["error"]["message"])
        self.assertEqual(self.view()["rev"], rev + 1)

    def test_without_the_option_the_public_name_is_refused(self):
        self.stop()
        self.public = None
        self.start()
        status, _, _ = self.request("GET", "/api/view", None, {"Host": "menlo.bet"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/intent", b'{"op": "level_up"}', {"Origin": "https://menlo.bet"})
        self.assertEqual(status, 403)

    def test_the_port_is_not_moved_when_a_web_server_points_at_it(self):
        # locally a taken port moves on to the next free one; behind a web server that would break the link
        other = tempfile.mkdtemp(prefix="menlo-app-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with self.assertRaises(OSError):
            server.start_server(self.port, folder=other, public=self.public)

    def test_the_page_asks_at_addresses_beside_itself(self):
        # "api/view", not "/api/view": under https://menlo.bet/coach/ the page must not ask https://menlo.bet/api/view
        static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "poker_coach", "app", "static")
        for name in ("controller.js", "render.js", "app.js", "index.html", "app.css"):
            with open(os.path.join(static, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(text, r"""fetch\(\s*["']/""", name)
            self.assertNotRegex(text, r"""(?:href|src)=["']/(?!/)""", name)
            self.assertNotRegex(text, r"""url\(\s*["']?/""", name)
        with open(os.path.join(static, "controller.js"), encoding="utf-8") as fh:
            text = fh.read()
        for address in ('fetch("api/view"', 'fetch("api/intent"', 'fetch("api/advice?rev="'):
            self.assertIn(address, text)


if __name__ == "__main__":
    unittest.main()
