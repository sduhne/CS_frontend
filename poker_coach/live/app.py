"""The live loop, its window, the setup and the session log.

    python3 -m poker_coach live-setup                 # mark the table and every box on it once
    python3 -m poker_coach live-teach                 # label what the reader does not know yet
    python3 -m poker_coach live                       # run: a small window shows each suggestion
    python3 -m poker_coach live-test --image shot.png # one saved screenshot -> reading and suggestion

The default reader runs on this computer (``local.py``): no network, no key,
no cost.  ``--reader vision`` sends the screenshot to Claude instead.

Settings live in ``tournament/live.json`` (git-ignored), the local reader's
files in ``tournament/reader/``.  Each session writes
``tournament/live-log/<time>/reads.jsonl`` with every reading, suggestion,
time and cost, plus the screenshots (``--no-save`` to keep only the text).
The packaged program keeps all of it in ``PokerCoach`` in the home folder.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from dataclasses import asdict, dataclass, field

from .capture import ButtonWatch, ChangeWatch, Grabber, Rect, dpi_aware, thumb
from .decide import DEFAULT_MARKERS, HandMemory, LiveSettings, Suggestion, suggest
from .reader import DEFAULT_EFFORT, DEFAULT_MAX_PX, DEFAULT_MODEL, ClaudeReader, JsonReader, ReadError, ReadResult

if getattr(sys, "frozen", False):                 # the packaged program: keep files in the home folder
    ROOT = os.path.join(os.path.expanduser("~"), "PokerCoach")
else:
    ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tournament")
CONFIG_PATH = os.path.join(ROOT, "live.json")
LOG_ROOT = os.path.join(ROOT, "live-log")
LAYOUT_PATH = os.path.join(ROOT, "reader", "layout.json")
BOOK_PATH = os.path.join(ROOT, "reader", "book.json")


@dataclass
class LiveConfig:
    region: list[int] | None = None          # left, top, width, height of the table on the screen
    monitor: int = 1
    buttons: list[int] | None = None         # the action-button area, relative to the region
    baseline: list[int] | None = None        # how that area looks when it is not your turn
    baselines: list | None = None            # more such looks, added with "Not my turn"
    opponents: str = "unknown"               # how the table plays: unknown, loose, tight, station...
    markers: list[str] = field(default_factory=lambda: list(DEFAULT_MARKERS))
    mode: str = "tag"
    reader: str = "local"                     # local (this computer, no network) or vision (Claude)
    seats: int = 6                            # seats at the table, for the local reader's setup
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_px: int = DEFAULT_MAX_PX
    min_gap: float = 4.0
    save_images: bool = True
    goal: str = "itm"
    entrants: int | None = None
    paid: int | None = None
    buyin: float | None = None

    @classmethod
    def load(cls, path: str | None = None) -> "LiveConfig":
        path = path or CONFIG_PATH
        if not os.path.exists(path):
            return cls()
        with open(path) as fh:
            data = json.load(fh)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: str | None = None) -> None:
        path = path or CONFIG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(asdict(self), fh, indent=1)

    def settings(self) -> LiveSettings:
        return LiveSettings(mode=self.mode, markers=tuple(self.markers), goal=self.goal,
                            entrants=self.entrants, paid=self.paid, buyin=self.buyin,
                            opponents=self.opponents)

    def idle_looks(self) -> list:
        """Every look of the action-button area that means "not your turn"."""
        return ([self.baseline] if self.baseline else []) + list(self.baselines or [])


# --------------------------------------------------------------------------
# Session log
# --------------------------------------------------------------------------

class SessionLog:
    """Every reading and suggestion of a session, for review and research."""

    def __init__(self, save_images: bool = True, root: str | None = None):
        self.dir = os.path.join(root or LOG_ROOT, time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(self.dir, exist_ok=True)
        self.save_images = save_images
        self.count = 0
        self.cost = 0.0

    def record(self, image, result: ReadResult | None, sug: Suggestion | None, error: str = "") -> None:
        self.count += 1
        entry = {"n": self.count, "time": time.strftime("%H:%M:%S"), "error": error}
        if result is not None:
            self.cost += result.cost
            entry.update(seconds=round(result.seconds, 2), model=result.model, input_tokens=result.input_tokens,
                         output_tokens=result.output_tokens, cost=round(result.cost, 5),
                         reading=result.table.model_dump())
        if sug is not None:
            entry["suggestion"] = asdict(sug)
        if image is not None and self.save_images:
            name = f"{self.count:04d}.png"
            image.save(os.path.join(self.dir, name))
            entry["image"] = name
        with open(os.path.join(self.dir, "reads.jsonl"), "a") as fh:
            fh.write(json.dumps(entry) + "\n")


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------

@dataclass
class Update:
    """What the window shows: a status line, or a suggestion."""
    status: str = ""
    suggestion: Suggestion | None = None
    seconds: float = 0.0
    cost: float = 0.0
    session_cost: float = 0.0


OBSERVE_EVERY = 0.5          # seconds between the local reader's looks when it is not your turn


def make_reader(cfg: LiveConfig):
    """The reader the settings ask for: local (needs the setup) or Claude's vision."""
    if cfg.reader == "vision":
        return ClaudeReader(cfg.model, cfg.effort, cfg.max_px)
    from .local import Layout, LocalReader
    from .vision import Book

    if not os.path.exists(LAYOUT_PATH):
        raise ReadError("the local reader is not set up: run live-setup (or Set up in the launcher) first")
    layout = Layout.load(LAYOUT_PATH)
    missing = layout.problems()
    if missing:
        raise ReadError("the setup is missing " + ", ".join(missing) + ": run live-setup again")
    return LocalReader(layout, Book.load(BOOK_PATH), cfg.buttons, cfg.idle_looks())


class Worker(threading.Thread):
    """Grabs the table, reads it when it is the player's turn, posts suggestions.

    The local reader costs nothing, so with it the loop looks all the time:
    between turns to follow the hand (who raised, who bet, the blinds), and on
    the player's turn until two readings in a row agree; then it advises, and
    again whenever the spot changes."""

    def __init__(self, cfg: LiveConfig, out: "queue.Queue[Update]", reader=None, grabber=None,
                 poll: float = 0.25):
        super().__init__(daemon=True)
        self.cfg, self.out, self.reader, self.grabber, self.poll = cfg, out, reader, grabber, poll
        self.force = threading.Event()
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.idle = threading.Event()             # "Not my turn": the buttons' look now is an idle look

    def run(self) -> None:
        cfg = self.cfg
        try:
            grabber = self.grabber or Grabber(Rect(*cfg.region) if cfg.region else None, cfg.monitor)
            reader = self.reader or make_reader(cfg)
        except Exception as exc:                      # no screen access, no setup, no SDK, no key...
            self.out.put(Update(status=f"cannot start: {exc}"))
            return
        if hasattr(reader, "observe"):
            self._run_local(grabber, reader)
        else:
            self._run_vision(grabber, reader)

    # -- the local reader: look all the time ------------------------------
    def _run_local(self, grabber, reader) -> None:
        from .local import signature

        cfg = self.cfg
        settings = cfg.settings()
        memory = HandMemory()
        log = SessionLog(cfg.save_images)
        has_turn = bool(reader.buttons and reader.baselines)
        how = ("advises when your action buttons appear" if has_turn else
               "no action-button area marked, so it advises whenever you hold cards: check that it is your turn")
        self.out.put(Update(status=f"watching ({cfg.mode} mode, local reader): {how}. Log: {log.dir}"))
        prev = shown = None
        was_active = False
        last_look = last_unknown = 0.0
        while not self.stopped.is_set():
            try:
                image = grabber.grab()
            except Exception as exc:
                self.out.put(Update(status=f"screen grab failed: {exc}"))
                time.sleep(2.0)
                continue
            if self.idle.is_set():
                self.idle.clear()
                look = reader.turn_look(image)
                if look:
                    reader.baselines.append(look)
                    cfg.baselines = (cfg.baselines or []) + [look]
                    cfg.save()
                    has_turn = True
                    self.out.put(Update(status="noted: the buttons looking like this is not your turn"))
                else:
                    self.out.put(Update(status="mark the action buttons in the setup first"))
            force = self.force.is_set()
            active = reader.hero_turn(image) if has_turn else True
            now = time.time()
            if not force and (not active or self.paused.is_set()):
                if was_active:
                    was_active, prev, shown = False, None, None
                    self.out.put(Update(status="waiting for your turn"))
                if now - last_look >= OBSERVE_EVERY:      # follow the hand between turns
                    last_look = now
                    seen = reader.observe(image)
                    if seen is not None:
                        if not seen.blocking:
                            memory.observe(seen.table)
                        elif now - last_unknown > 10.0 and log.count < 500:
                            last_unknown = now            # kept for "teach from the last session"
                            log.record(image, seen, None, "; ".join(seen.blocking))
                time.sleep(self.poll)
                continue
            was_active = True
            try:
                result = reader.read(image)
            except ReadError as exc:
                self.out.put(Update(status=f"could not read: {exc}"))
                time.sleep(1.0)
                continue
            sig = signature(result.table)
            if force or (sig == prev and sig != shown):   # the same twice in a row: the table has settled
                self.force.clear()
                sug = suggest(result.table, settings, memory, force=force, blocking=result.blocking)
                if sug.kind in ("act", "error") or force:
                    log.record(image, result, sug)
                self.out.put(Update(suggestion=sug, seconds=result.seconds))
                shown = sig
            elif not result.blocking:
                memory.observe(result.table)
            prev = sig
            time.sleep(self.poll)

    # -- a reader that costs per reading: once per decision -----------------
    def _run_vision(self, grabber, reader) -> None:
        cfg = self.cfg
        if cfg.buttons and cfg.baseline:
            watch = ButtonWatch(Rect(*cfg.buttons), cfg.baseline)
            how = "reads when your action buttons appear"
        else:
            watch = ChangeWatch(cfg.min_gap)
            how = f"reads when the table changes (at most every {cfg.min_gap:g}s); run live-setup to read only " \
                  "on your turn"
        settings = cfg.settings()
        memory = HandMemory()
        log = SessionLog(cfg.save_images)
        self.out.put(Update(status=f"watching ({cfg.mode} mode, {cfg.model}): {how}. Log: {log.dir}"))
        while not self.stopped.is_set():
            try:
                image = grabber.grab()
            except Exception as exc:
                self.out.put(Update(status=f"screen grab failed: {exc}"))
                time.sleep(2.0)
                continue
            fire = watch.update(image)
            force = self.force.is_set()
            if (fire and not self.paused.is_set()) or force:
                self.force.clear()
                self.out.put(Update(status="reading the table..."))
                try:
                    result = reader.read(image)
                except ReadError as exc:
                    log.record(image, None, None, str(exc))
                    self.out.put(Update(status=f"could not read: {exc}"))
                    continue
                sug = suggest(result.table, settings, memory, force=force,
                              blocking=getattr(result, "blocking", None))
                log.record(image, result, sug)
                self.out.put(Update(suggestion=sug, seconds=result.seconds, cost=result.cost,
                                    session_cost=log.cost))
            time.sleep(self.poll)


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------

COLORS = {"go": "#1E9E5A", "calm": "#2F6FD6", "fold": "#6F6F78", "blocked": "#C0392B", "error": "#D35400",
          "wait": "#6F6F78"}


def _tone(sug: Suggestion) -> str:
    if sug.kind != "act":
        return {"blocked": "blocked", "error": "error"}.get(sug.kind, "wait")
    a = sug.action.upper()
    if a.startswith("FOLD"):
        return "fold"
    if a.startswith(("CHECK", "CALL")):
        return "calm"
    return "go"


def _overlap(region, window) -> bool:
    """The window (left, top, width, height) covers part of the table region."""
    l, t, w, h = region
    x, y, ww, wh = window
    return x < l + w and x + ww > l and y < t + h and y + wh > t


def _beside(region, screen_w: int, screen_h: int, w: int, h: int) -> str:
    """A place for the coach's window that does not cover the table: '+x+y', or '' if there is none."""
    if not region:
        return ""
    l, t, rw, rh = region
    for x, y in ((l + rw + 8, t), (l - w - 8, t), (l, t + rh + 40), (l, t - h - 60)):
        if 0 <= x and x + w <= screen_w and 0 <= y and y + h + 40 <= screen_h:
            return f"+{int(x)}+{int(y)}"
    return ""


def run_window(cfg: LiveConfig, worker: Worker, out: "queue.Queue[Update]", master=None) -> None:
    import tkinter as tk

    if master is None:
        dpi_aware()
    root = tk.Toplevel(master) if master is not None else tk.Tk()
    root.title("Coach · play money")
    root.attributes("-topmost", True)
    root.configure(bg="#0A0A0B")
    root.geometry("480x300" + _beside(cfg.region, root.winfo_screenwidth(), root.winfo_screenheight(), 480, 300))
    fg, sub = "#FFFFFF", "#B9B9C1"
    action = tk.Label(root, text="watching", font=("Helvetica", 24, "bold"), fg=fg, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=456)
    action.pack(fill="x", padx=12, pady=(10, 0))
    # what it saw: your cards, seat, stack in big blinds, what happened before you
    info = tk.Label(root, text="", font=("Helvetica", 11, "bold"), fg="#FFD60A", bg="#0A0A0B", anchor="w",
                    justify="left", wraplength=456)
    info.pack(fill="x", padx=12)
    reason = tk.Label(root, text="", font=("Helvetica", 12), fg=fg, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=456)
    reason.pack(fill="x", padx=12, pady=(4, 0))
    detail = tk.Label(root, text="", font=("Helvetica", 10), fg=sub, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=456)
    detail.pack(fill="x", padx=12)
    bar = tk.Frame(root, bg="#0A0A0B")
    bar.pack(side="bottom", fill="x", padx=12, pady=8)
    status = tk.Label(root, text="", font=("Helvetica", 9), fg=sub, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=456)
    status.pack(side="bottom", fill="x", padx=12)

    def read_now() -> None:
        worker.force.set()

    def pause() -> None:
        if worker.paused.is_set():
            worker.paused.clear()
            pause_btn.config(text="Pause")
        else:
            worker.paused.set()
            pause_btn.config(text="Resume")

    def quit_() -> None:
        worker.stopped.set()
        root.destroy()

    tk.Button(bar, text="Read now", command=read_now).pack(side="left")
    pause_btn = tk.Button(bar, text="Pause", command=pause)
    pause_btn.pack(side="left", padx=6)
    # it advised although it was not your turn: the buttons' look now is added to the idle looks
    tk.Button(bar, text="Not my turn", command=worker.idle.set).pack(side="left")
    tk.Button(bar, text="Quit", command=quit_).pack(side="right")

    def poll() -> None:
        try:
            while True:
                u = out.get_nowait()
                if u.suggestion is None:
                    status.config(text=u.status)
                    if u.status == "waiting for your turn":       # the advice shown is for a spot that is over
                        action.config(fg="#4A4A52")
                        reason.config(fg="#6F6F78")
                    continue
                s = u.suggestion
                tone = COLORS[_tone(s)]
                reason.config(fg=fg)
                action.config(text=s.action or {"wait": "WAIT", "error": "NO ADVICE", "blocked": "BLOCKED"}.get(
                    s.kind, s.kind.upper()), fg=tone)
                info.config(text=s.info)
                reason.config(text=s.reason)
                detail.config(text="\n".join(s.details[:2] + [f"! {w}" for w in s.warnings[:2]]))
                status.config(text=f"{time.strftime('%H:%M:%S')} · read in {u.seconds:.2f}s"
                                   + (f" · ${u.cost:.3f} · session ${u.session_cost:.2f}" if u.session_cost else ""))
        except queue.Empty:
            pass
        if cfg.region and _overlap(cfg.region, (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(),
                                                root.winfo_height())):
            status.config(text="MOVE THIS WINDOW OFF THE POKER TABLE: what it covers cannot be read", fg="#FF6B5E")
            covered["on"] = True
        elif covered["on"]:
            covered["on"] = False
            status.config(text="", fg=sub)
        root.after(100, poll)

    covered = {"on": False}
    root.protocol("WM_DELETE_WINDOW", quit_)
    poll()
    if master is not None:
        master.wait_window(root)
    else:
        root.mainloop()


def run_console(worker: Worker, out: "queue.Queue[Update]") -> None:
    """No window: print each suggestion; press Enter to read now, Ctrl+C to stop."""

    def keys() -> None:
        while not worker.stopped.is_set():
            try:
                input()
            except EOFError:
                return
            worker.force.set()

    threading.Thread(target=keys, daemon=True).start()
    try:
        while worker.is_alive():
            try:
                u = out.get(timeout=0.5)
            except queue.Empty:
                continue
            if u.suggestion is None:
                print(f"[{time.strftime('%H:%M:%S')}] {u.status}", flush=True)
            else:
                cost = f", ${u.cost:.3f} (session ${u.session_cost:.2f})" if u.session_cost else ""
                print(f"\n[{time.strftime('%H:%M:%S')}] read in {u.seconds:.2f}s{cost}\n{u.suggestion.text()}",
                      flush=True)
    except KeyboardInterrupt:
        worker.stopped.set()


def run(cfg: LiveConfig, window: bool = True) -> int:
    dpi_aware()
    out: "queue.Queue[Update]" = queue.Queue()
    worker = Worker(cfg, out)
    worker.start()
    if window:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print("tkinter is not installed: showing suggestions here instead (Enter = read now)")
            window = False
    if window:
        run_window(cfg, worker, out)
    else:
        run_console(worker, out)
    worker.stopped.set()
    return 0


# --------------------------------------------------------------------------
# Setup: mark the table and the action buttons
# --------------------------------------------------------------------------

def setup_from_rects(cfg: LiveConfig, region: Rect, buttons: Rect | None) -> LiveConfig:
    """Command-line setup: ``region`` in screen coordinates, ``buttons`` relative to it.

    The button area's look is taken now, so it must not be your turn.  On a
    high-DPI screen a grab has more pixels than screen coordinates; the button
    area is stored in the grab's pixels."""
    cfg.region = region.as_list()
    cfg.buttons = cfg.baseline = None
    if buttons is not None:
        image = Grabber(region, cfg.monitor).grab()
        sx, sy = image.width / region.width, image.height / region.height
        px = Rect(int(buttons.left * sx), int(buttons.top * sy), int(buttons.width * sx), int(buttons.height * sy))
        cfg.buttons = px.as_list()
        cfg.baseline = thumb(image.crop(px.box()))
    return cfg


def setup_window(cfg: LiveConfig) -> LiveConfig | None:
    """Two drags on a screenshot: the table, then the action-button area."""
    import tkinter as tk
    from PIL import Image, ImageTk

    from .capture import screen_grabber

    dpi_aware()
    with screen_grabber() as sct:
        mon = sct.monitors[cfg.monitor if cfg.monitor < len(sct.monitors) else 1]
        shot = sct.grab(mon)
        full = Image.frombytes("RGB", shot.size, shot.rgb)
    scale = min(1.0, 1100.0 / full.width, 680.0 / full.height)
    view = full.resize((int(full.width * scale), int(full.height * scale)))
    root = tk.Tk()
    root.title("Coach setup")
    root.attributes("-topmost", True)
    note = tk.Label(root, font=("Helvetica", 13), justify="left", anchor="w")
    note.pack(fill="x", padx=10, pady=6)
    canvas = tk.Canvas(root, width=view.width, height=view.height, cursor="crosshair")
    canvas.pack(padx=10, pady=(0, 10))
    photo = ImageTk.PhotoImage(view)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    state = {"step": 0, "start": None, "box": None, "rect": None, "table": None, "buttons": None, "done": False}
    steps = ("1/2  Drag a box around the whole poker table, then press Enter.",
             "2/2  Drag a box around where your Fold / Call / Raise buttons appear, then press Enter.\n"
             "      It must NOT be your turn in this screenshot. Press S to skip (then it reads when the table changes).")
    note.config(text=steps[0])

    def down(e):
        state["start"] = (e.x, e.y)
        if state["box"]:
            canvas.delete(state["box"])
        state["box"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#FFD60A", width=2)

    def drag(e):
        if state["start"]:
            x0, y0 = state["start"]
            canvas.coords(state["box"], x0, y0, e.x, e.y)
            state["rect"] = (min(x0, e.x), min(y0, e.y), abs(e.x - x0), abs(e.y - y0))

    def to_pixels(r) -> Rect:                          # view -> screenshot pixels
        x, y, w, h = r
        return Rect(int(x / scale), int(y / scale), int(w / scale), int(h / scale))

    def enter(_e=None):
        if not state["rect"] or state["rect"][2] < 10 or state["rect"][3] < 10:
            return
        if state["step"] == 0:
            state["table"] = to_pixels(state["rect"])
            state["step"], state["rect"], state["start"] = 1, None, None
            canvas.delete(state["box"])
            state["box"] = None
            note.config(text=steps[1])
        else:
            state["buttons"] = to_pixels(state["rect"])
            state["done"] = True
            root.destroy()

    def skip(_e=None):
        if state["step"] == 1:
            state["done"] = True
            root.destroy()

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", drag)
    root.bind("<Return>", enter)
    root.bind("<s>", skip)
    root.bind("<S>", skip)
    root.mainloop()
    if not state["done"] or state["table"] is None:
        return None
    t = state["table"]
    # screenshot pixels -> screen coordinates (they differ on high-DPI screens)
    sx, sy = full.width / mon["width"], full.height / mon["height"]
    cfg.region = [int(mon["left"] + t.left / sx), int(mon["top"] + t.top / sy), int(t.width / sx), int(t.height / sy)]
    cfg.buttons = cfg.baseline = None
    if state["buttons"] is not None:
        b = state["buttons"]
        rel = Rect(b.left - t.left, b.top - t.top, b.width, b.height)   # in the grab's pixels
        cfg.buttons = rel.as_list()
        cfg.baseline = thumb(full.crop(t.box()).crop(rel.box()))
    return cfg


# --------------------------------------------------------------------------
# One reading, printed (no screen needed)
# --------------------------------------------------------------------------

def describe_reading(r) -> str:
    from ..ranges import position_name
    from .decide import HandMemory as _HM

    n = len(r.seats)
    order = _HM._order(r) if any(s.has_button for s in r.seats) else []
    pos = {k: position_name(n - 1 - i, n) for i, k in enumerate(order)}
    bb = r.big_blind if (r.big_blind and not r.amounts_in_bb) else (1.0 if r.amounts_in_bb else None)
    seats = []
    for k, s in enumerate(r.seats):
        flags = "".join([" (you)" if s.is_hero else "", " D" if s.has_button else "", " folded" if s.folded else "",
                         " all-in" if s.all_in else "", " away" if s.sitting_out else ""])
        stack = "?" if s.stack is None else f"{s.stack:,.0f}" + (f" = {s.stack / bb:.0f}bb" if bb else "")
        bet = f" bet {s.bet:,.0f}" if s.bet else ""
        seats.append(f"{pos.get(k, '?') + ' ' if pos else ''}{s.name or '?'} {stack}{bet}{flags}")
    blinds = f"{r.small_blind or '?'}/{r.big_blind or '?'}" + (f" ante {r.ante:g} ({r.ante_kind})" if r.ante else "")
    lines = [f"table: {r.table_text or '-'} | money: {r.money_text or '-'} | blinds {blinds}"
             + (" | amounts in bb" if r.amounts_in_bb else ""),
             f"cards: {' '.join(r.hero_cards) or '-'} | board: {' '.join(r.board) or '-'} | "
             f"pot: middle {r.middle_pot}, total {r.total_pot} | your turn: {'yes' if r.hero_to_act else 'no'}",
             "seats (clockwise from you):"] + [f"  {x}" for x in seats]
    if r.players_left or r.places_paid:
        lines.append(f"tournament: {r.players_left} left, {r.places_paid} paid, average {r.average_stack}")
    if r.unreadable:
        lines.append(f"unreadable: {r.unreadable}")
    return "\n".join(lines)


def test_once(cfg: LiveConfig, image_path: str | None = None, json_path: str | None = None,
              force: bool = True, save_json: str | None = None, reader=None) -> str:
    if json_path:
        result = JsonReader(json_path).read()
    else:
        from PIL import Image

        result = (reader or make_reader(cfg)).read(Image.open(image_path).convert("RGB"))
    if save_json:
        with open(save_json, "w") as fh:
            json.dump(result.table.model_dump(), fh, indent=1)
    sug = suggest(result.table, cfg.settings(), HandMemory(), force=force,
                  blocking=getattr(result, "blocking", None))
    if result.cost:
        head = (f"read by {result.model} in {result.seconds:.1f}s, ${result.cost:.4f} "
                f"({result.input_tokens} in, {result.output_tokens} out tokens)")
    else:
        head = f"read by {result.model}" + (f" in {result.seconds * 1000:.0f} ms" if result.seconds else "")
    return f"{head}\n{describe_reading(result.table)}\n\n{sug.text()}"
