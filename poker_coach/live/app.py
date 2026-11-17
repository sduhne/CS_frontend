"""The live loop, its window, the setup and the session log.

    python3 -m poker_coach live-setup                 # mark the table and the action buttons once
    python3 -m poker_coach live                       # run: a small window shows each suggestion
    python3 -m poker_coach live-test --image shot.png # one saved screenshot -> reading and suggestion

Settings live in ``tournament/live.json`` (git-ignored).  Each session writes
``tournament/live-log/<time>/reads.jsonl`` with every reading, suggestion,
time and cost, plus the screenshots (``--no-save`` to keep only the text).
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import asdict, dataclass, field

from .capture import ButtonWatch, ChangeWatch, Grabber, Rect, thumb
from .decide import DEFAULT_MARKERS, HandMemory, LiveSettings, Suggestion, suggest
from .reader import DEFAULT_EFFORT, DEFAULT_MAX_PX, DEFAULT_MODEL, ClaudeReader, JsonReader, ReadError, ReadResult

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tournament")
CONFIG_PATH = os.path.join(ROOT, "live.json")
LOG_ROOT = os.path.join(ROOT, "live-log")


@dataclass
class LiveConfig:
    region: list[int] | None = None          # left, top, width, height of the table on the screen
    monitor: int = 1
    buttons: list[int] | None = None         # the action-button area, relative to the region
    baseline: list[int] | None = None        # how that area looks when it is not your turn
    markers: list[str] = field(default_factory=lambda: list(DEFAULT_MARKERS))
    mode: str = "tag"
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
    def load(cls, path: str = CONFIG_PATH) -> "LiveConfig":
        if not os.path.exists(path):
            return cls()
        with open(path) as fh:
            data = json.load(fh)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: str = CONFIG_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(asdict(self), fh, indent=1)

    def settings(self) -> LiveSettings:
        return LiveSettings(mode=self.mode, markers=tuple(self.markers), goal=self.goal,
                            entrants=self.entrants, paid=self.paid, buyin=self.buyin)


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


class Worker(threading.Thread):
    """Grabs the table, reads it when it is the player's turn, posts suggestions."""

    def __init__(self, cfg: LiveConfig, out: "queue.Queue[Update]", reader=None, grabber=None,
                 poll: float = 0.25):
        super().__init__(daemon=True)
        self.cfg, self.out, self.reader, self.grabber, self.poll = cfg, out, reader, grabber, poll
        self.force = threading.Event()
        self.paused = threading.Event()
        self.stopped = threading.Event()

    def run(self) -> None:
        cfg = self.cfg
        try:
            grabber = self.grabber or Grabber(Rect(*cfg.region) if cfg.region else None, cfg.monitor)
            reader = self.reader or ClaudeReader(cfg.model, cfg.effort, cfg.max_px)
        except Exception as exc:                      # no screen access, no SDK, no key...
            self.out.put(Update(status=f"cannot start: {exc}"))
            return
        if cfg.buttons and cfg.baseline:
            watch = ButtonWatch(Rect(*cfg.buttons), cfg.baseline)
            how = "reads when your action buttons appear"
        else:
            watch = ChangeWatch(cfg.min_gap)
            how = f"reads when the table changes (at most every {cfg.min_gap:g}s); run live-setup to read only on your turn"
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
                sug = suggest(result.table, settings, memory, force=force)
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


def run_window(cfg: LiveConfig, worker: Worker, out: "queue.Queue[Update]") -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("Coach · play money")
    root.attributes("-topmost", True)
    root.configure(bg="#0A0A0B")
    root.geometry("420x230")
    fg, sub = "#FFFFFF", "#B9B9C1"
    action = tk.Label(root, text="watching", font=("Helvetica", 24, "bold"), fg=fg, bg="#0A0A0B", anchor="w")
    action.pack(fill="x", padx=12, pady=(10, 0))
    info = tk.Label(root, text="", font=("Helvetica", 11), fg=sub, bg="#0A0A0B", anchor="w")
    info.pack(fill="x", padx=12)
    reason = tk.Label(root, text="", font=("Helvetica", 12), fg=fg, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=396)
    reason.pack(fill="x", padx=12, pady=(4, 0))
    detail = tk.Label(root, text="", font=("Helvetica", 10), fg=sub, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=396)
    detail.pack(fill="x", padx=12)
    bar = tk.Frame(root, bg="#0A0A0B")
    bar.pack(side="bottom", fill="x", padx=12, pady=8)
    status = tk.Label(root, text="", font=("Helvetica", 9), fg=sub, bg="#0A0A0B", anchor="w",
                      justify="left", wraplength=396)
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
    tk.Button(bar, text="Quit", command=quit_).pack(side="right")

    def poll() -> None:
        try:
            while True:
                u = out.get_nowait()
                if u.suggestion is None:
                    status.config(text=u.status)
                    continue
                s = u.suggestion
                tone = COLORS[_tone(s)]
                action.config(text=s.action or s.kind.upper(), fg=tone)
                info.config(text=s.info)
                reason.config(text=s.reason)
                detail.config(text="\n".join(s.details[:2] + [f"! {w}" for w in s.warnings[:2]]))
                status.config(text=f"{time.strftime('%H:%M:%S')} · read in {u.seconds:.1f}s · "
                                   f"${u.cost:.3f} · session ${u.session_cost:.2f}")
        except queue.Empty:
            pass
        root.after(100, poll)

    root.protocol("WM_DELETE_WINDOW", quit_)
    poll()
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
                print(f"\n[{time.strftime('%H:%M:%S')}] read in {u.seconds:.1f}s, ${u.cost:.3f} "
                      f"(session ${u.session_cost:.2f})\n{u.suggestion.text()}", flush=True)
    except KeyboardInterrupt:
        worker.stopped.set()


def run(cfg: LiveConfig, window: bool = True) -> int:
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
    import mss
    import tkinter as tk
    from PIL import Image, ImageTk

    with mss.mss() as sct:
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
    seats = []
    for s in r.seats:
        flags = "".join([" (you)" if s.is_hero else "", " D" if s.has_button else "", " folded" if s.folded else "",
                         " all-in" if s.all_in else "", " away" if s.sitting_out else ""])
        stack = "?" if s.stack is None else f"{s.stack:,.0f}"
        bet = f" bet {s.bet:,.0f}" if s.bet else ""
        seats.append(f"{s.name or '?'} {stack}{bet}{flags}")
    blinds = f"{r.small_blind or '?'}/{r.big_blind or '?'}" + (f" ante {r.ante:g} ({r.ante_kind})" if r.ante else "")
    lines = [f"table: {r.table_text or '-'} | money: {r.money_text or '-'} | blinds {blinds}"
             + (" | amounts in bb" if r.amounts_in_bb else ""),
             f"cards: {' '.join(r.hero_cards) or '-'} | board: {' '.join(r.board) or '-'} | "
             f"pot: middle {r.middle_pot}, total {r.total_pot} | your turn: {'yes' if r.hero_to_act else 'no'}",
             "seats (clockwise from you): " + " | ".join(seats)]
    if r.players_left or r.places_paid:
        lines.append(f"tournament: {r.players_left} left, {r.places_paid} paid, average {r.average_stack}")
    if r.unreadable:
        lines.append(f"unreadable: {r.unreadable}")
    return "\n".join(lines)


def test_once(cfg: LiveConfig, image_path: str | None = None, json_path: str | None = None,
              force: bool = True, save_json: str | None = None) -> str:
    if json_path:
        result = JsonReader(json_path).read()
    else:
        from PIL import Image

        result = ClaudeReader(cfg.model, cfg.effort, cfg.max_px).read(Image.open(image_path))
    if save_json:
        with open(save_json, "w") as fh:
            json.dump(result.table.model_dump(), fh, indent=1)
    sug = suggest(result.table, cfg.settings(), HandMemory(), force=force)
    head = f"read by {result.model}" + (f" in {result.seconds:.1f}s, ${result.cost:.4f} "
                                         f"({result.input_tokens} in, {result.output_tokens} out tokens)"
                                         if result.seconds else "")
    return f"{head}\n{describe_reading(result.table)}\n\n{sug.text()}"
