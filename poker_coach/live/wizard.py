"""The windows of the local reader: setup, teaching and the launcher.

* ``setup_local``: mark the table on the screen, then every box on it
  (cards, stacks, bets, the button places, the pot...), step by step.  With
  ``redo`` it marks only some boxes again.
* ``teach_window``: shows each box the reader cannot read yet and asks what it
  shows; every answer becomes an example in the book.
* ``launcher``: one small window with Set up, Teach, Check and Start, for
  people who would rather not use the command line (and for the packaged .exe).

Screenshots come in through functions, so the windows can be tested with
pictures instead of a screen.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from PIL import Image

from .capture import Rect, dpi_aware, screen_grabber, thumb
from .local import PIECES, Layout, SeatLayout, TeachItem, learn, learn_pieces, teach_items
from .vision import UNKNOWN, Book, png_b64


@dataclass
class Step:
    key: str
    text: str
    optional: bool = False


def table_steps(seats: int) -> list[Step]:
    """Every box the local reader needs, in the order the wizard asks for them."""
    steps = [
        Step("marker", "Draw a box around something that only play-money tables show: the words Play Money, "
                       "or the play-chip icon. Without it the coach will not give advice."),
        Step("buttons", "Draw a box around where your Fold / Call / Raise buttons appear. It must NOT be your turn "
                        "in this screenshot (press G for a new one when it is not).", True),
        Step("hero1", "Your first card: a box around its top-left corner, the rank and the suit symbol, inside "
                      "the card (press G for a new screenshot once you have cards)."),
        Step("hero2", "Your second card: the same corner, the rank and the suit symbol."),
    ]
    for j in range(1, 6):
        steps.append(Step(f"board{j}", f"Board card {j}: a box around its top-left corner, rank and suit. "
                                       "Press G for a new screenshot once the cards are out. Needed for advice "
                                       "after the flop.", True))
    steps += [
        Step("pot", "The pot number. If the word Pot is part of it, include it. Needed for advice after the "
                    "flop.", True),
        Step("players_left", "Players left in the tournament, if the table shows it (S to skip).", True),
        Step("button_tpl", "A tight box around the dealer button (the D disc)."),
        Step("backs_tpl", "A tight box around one opponent's two face-down cards."),
    ]
    for k in range(1, seats + 1):
        who = "you" if k == 1 else ("the player on your left" if k == 2 else f"seat {k}")
        steps.append(Step(f"s{k}_stack", f"Seat {k} ({who}): the box where the stack number shows, only the "
                                         "number. Seats go clockwise from you."))
        steps.append(Step(f"s{k}_bet", f"Seat {k}: where this player's bet amount appears. Draw it a little "
                                       "wider than the number, but not over cards, chips or other text."))
        steps.append(Step(f"s{k}_button", f"Seat {k}: where the dealer button sits when this seat has it. "
                                          "A generous box is fine, as long as it cannot hold another seat's button."))
        if k > 1:
            steps.append(Step(f"s{k}_cards", f"Seat {k}: where this player's face-down cards show "
                                             "(a generous box is fine)."))
    return steps


def step_label(key: str) -> str:
    """A step's key in words, for the list of boxes to mark again."""
    fixed = {"marker": "play-money marker", "buttons": "your action buttons", "hero1": "your card 1",
             "hero2": "your card 2", "pot": "the pot", "players_left": "players left",
             "button_tpl": "the dealer button itself", "backs_tpl": "face-down cards (the picture)"}
    if key in fixed:
        return fixed[key]
    if key.startswith("board"):
        return f"board card {key[5:]}"
    seat, part = key[1:].split("_")
    return f"seat {seat} " + {"stack": "stack", "bet": "bet", "button": "button place", "cards": "cards area"}[part]


class BoxWizard:
    """Draw one box per step on a picture.  Enter saves, S skips an optional step,
    G takes a new screenshot, Backspace goes back, Esc cancels."""

    def __init__(self, image: Image.Image, steps: list[Step], title: str, grab=None, master=None,
                 fit=None, shown: dict | None = None):
        import tkinter as tk

        self.tk = tk
        self.image, self.steps, self.grab = image, steps, grab
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.attributes("-topmost", True)
        self.win.focus_force()
        if fit is None:                               # leave room for the text and the screen's edges
            fit = (max(480, self.win.winfo_screenwidth() - 80), max(320, self.win.winfo_screenheight() - 230))
        self.scale = min(1.0, fit[0] / image.width, fit[1] / image.height)
        self.note = tk.Label(self.win, font=("Helvetica", 13, "bold"), justify="left", anchor="w",
                             wraplength=max(480, int(image.width * self.scale)))
        self.note.pack(fill="x", padx=10, pady=(8, 0))
        self.keys = tk.Label(self.win, font=("Helvetica", 10), fg="#4A4A52", anchor="w")
        self.keys.pack(fill="x", padx=10)
        self.canvas = tk.Canvas(self.win, width=int(image.width * self.scale), height=int(image.height * self.scale),
                                cursor="crosshair", highlightthickness=0)
        self.canvas.pack(padx=10, pady=8)
        self.k = 0
        self.results: dict[str, Rect] = {}
        self.images: dict[str, Image.Image] = {}
        self.shown = dict(shown or {})                # boxes from an earlier setup, drawn for reference
        self.drag = None
        self.box = None
        self.done = False
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        for key, fn in (("<Return>", self._enter), ("<KP_Enter>", self._enter), ("<s>", self._skip),
                        ("<S>", self._skip), ("<g>", self._grab), ("<G>", self._grab),
                        ("<BackSpace>", self._back), ("<Escape>", self._cancel)):
            self.win.bind(key, fn)
        self._show_image()
        self._update()

    # drawing ------------------------------------------------------------
    def _show_image(self) -> None:
        from PIL import ImageTk

        view = self.image.resize((int(self.image.width * self.scale), int(self.image.height * self.scale)))
        self.photo = ImageTk.PhotoImage(view)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        s = self.scale
        for boxes, colour in ((self.shown, "#8E8E93"), (self.results, "#FFD60A")):
            for key, r in boxes.items():
                if boxes is self.shown and key in self.results:
                    continue
                self.canvas.create_rectangle(r.left * s, r.top * s, (r.left + r.width) * s, (r.top + r.height) * s,
                                             outline=colour, width=1)
                self.canvas.create_text(r.left * s + 2, r.top * s, text=key, anchor="sw", fill=colour,
                                        font=("Helvetica", 8))
        self.box = None

    def _update(self) -> None:
        step = self.steps[self.k]
        self.note.config(text=f"{self.k + 1}/{len(self.steps)}  {step.text}")
        keys = "Drag a box, then Enter to save · G: new screenshot · Backspace: back · Esc: cancel"
        if step.optional:
            keys += " · S: skip"
        self.keys.config(text=keys)
        self.drag = None

    def _down(self, e) -> None:
        if self.box:
            self.canvas.delete(self.box)
        self.drag = [e.x, e.y, e.x, e.y]
        self.box = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#2F6FD6", width=2)

    def _move(self, e) -> None:
        if self.drag:
            self.drag[2:] = [e.x, e.y]
            self.canvas.coords(self.box, *self.drag)

    def current(self) -> Rect | None:
        if not self.drag:
            return None
        x0, y0, x1, y1 = self.drag
        s = self.scale
        r = Rect(int(min(x0, x1) / s), int(min(y0, y1) / s), int(abs(x1 - x0) / s), int(abs(y1 - y0) / s))
        return r if r.width >= 4 and r.height >= 4 else None

    # keys ---------------------------------------------------------------
    def _enter(self, _e=None) -> None:
        r = self.current()
        if r is None:
            return
        key = self.steps[self.k].key
        self.results[key] = r
        self.images[key] = self.image
        self._next()

    def _skip(self, _e=None) -> None:
        if self.steps[self.k].optional:
            self.results.pop(self.steps[self.k].key, None)
            self._next()

    def _next(self) -> None:
        if self.k + 1 >= len(self.steps):
            self.done = True
            self.win.destroy()
            return
        self.k += 1
        self._show_image()
        self._update()

    def _back(self, _e=None) -> None:
        if self.k:
            self.k -= 1
            self.results.pop(self.steps[self.k].key, None)
            self._show_image()
            self._update()

    def _grab(self, _e=None) -> None:
        if self.grab is None:
            return
        img = hidden_grab(self.win, self.grab)        # this window must not be in the picture
        self.win.focus_force()
        if img.size == self.image.size:
            self.image = img
            self._show_image()
            self._update()

    def _cancel(self, _e=None) -> None:
        self.win.destroy()

    def run(self) -> dict[str, Rect] | None:
        self.win.wait_window()
        return self.results if self.done else None


def hidden_grab(window, grab, wait: float = 0.3):
    """Take a screenshot with ``window`` out of the way, then bring it back."""
    try:
        window.withdraw()
        window.update()
        time.sleep(wait)
        return grab()
    finally:
        window.deiconify()
        window.update()


class _Root:
    """The caller's window, or a hidden one for the command line."""

    def __init__(self, master=None):
        self.master, self.own = master, master is None

    def __enter__(self):
        if self.own:
            import tkinter as tk

            dpi_aware()
            self.master = tk.Tk()
            self.master.withdraw()
        return self.master

    def __exit__(self, *_):
        if self.own:
            self.master.destroy()


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

def marker_ok(text: str, markers) -> bool:
    """The marker's words must be one of the play-money words (the guard checks them on every read)."""
    low = (text or "").lower()
    return any(m and m.strip().lower() in low for m in markers)


def apply_boxes(lay: Layout, results: dict[str, Rect], images: dict[str, Image.Image], seats: int) -> Layout:
    """Put the wizard's boxes (and the templates cut from its screenshots) into a layout;
    what is not in ``results`` stays as it was."""
    def tpl(key):
        return png_b64(images[key].crop(results[key].box()))

    while len(lay.hero_cards) < 2:
        lay.hero_cards.append(None)
    while len(lay.seats) < seats:
        lay.seats.append(SeatLayout())
    board = {j: (lay.board[j - 1] if j <= len(lay.board) else None) for j in range(1, 6)}
    for key, r in results.items():
        box = r.as_list()
        if key == "marker":
            lay.marker, lay.marker_template = box, tpl(key)
        elif key in ("hero1", "hero2"):
            lay.hero_cards[int(key[-1]) - 1] = box
        elif key.startswith("board"):
            board[int(key[5:])] = box
        elif key in ("pot", "players_left"):
            setattr(lay, key, box)
        elif key == "button_tpl":
            lay.button_template = tpl(key)
        elif key == "backs_tpl":
            lay.backs_template = tpl(key)
        elif key.startswith("s") and "_" in key:
            seat, part = key[1:].split("_")
            setattr(lay.seats[int(seat) - 1], part, box)
    lay.board = []
    for j in range(1, 6):                             # the board is read left to right until a gap
        if not board[j]:
            break
        lay.board.append(board[j])
    return lay


def layout_boxes(lay: Layout) -> dict[str, Rect]:
    """The boxes of a layout by wizard key, to draw them for reference."""
    out = {}

    def put(key, box):
        if box:
            out[key] = Rect(*box)

    put("marker", lay.marker)
    for k, b in enumerate(lay.hero_cards, 1):
        put(f"hero{k}", b)
    for k, b in enumerate(lay.board, 1):
        put(f"board{k}", b)
    put("pot", lay.pot)
    put("players_left", lay.players_left)
    for k, s in enumerate(lay.seats, 1):
        for part in ("stack", "bet", "button", "cards"):
            put(f"s{k}_{part}", getattr(s, part))
    return out


def layout_from(results: dict[str, Rect], images: dict[str, Image.Image], table_size, seats: int,
                pot_includes_bets: bool = True, marker_text: str = "") -> Layout:
    """A new layout from the wizard's boxes (and the screenshots they were drawn on)."""
    lay = Layout(size=list(table_size), pot_includes_bets=pot_includes_bets, marker_text=marker_text)
    return apply_boxes(lay, results, images, seats)


def _ask_marker(cfg, root, ask_marker):
    words = ""
    while True:
        if ask_marker is None:
            from tkinter import simpledialog
            words = simpledialog.askstring(
                "Coach setup", "What does the play-money marker you boxed say?\n(for example: Play Money)",
                initialvalue=words or "Play Money", parent=root)
        else:
            words = ask_marker()
        if words is None:
            return None
        if marker_ok(words, cfg.markers):
            return words.strip()
        if ask_marker is not None:
            return None
        from tkinter import messagebox
        messagebox.showwarning("Coach setup", "The coach works only at play-money tables, and the marker must "
                               "say so (" + ", ".join(cfg.markers) + "). If your client words it differently, "
                               "add the words with --marker.", parent=root)


def _ask_pot(root, ask_pot) -> bool:
    if ask_pot is not None:
        return ask_pot()
    from tkinter import messagebox
    return messagebox.askyesno(
        "Coach setup", "Does the pot number include the bets that are still in front of the players?"
                       "\n\n(Look at a hand where someone has bet: if the pot grew when they bet, "
                       "answer Yes.)", parent=root)


def setup_local(cfg, layout_path: str, book_path: str, seats: int, grab_screen=None, grab_table=None,
                master=None, ask_pot=None, ask_marker=None, teach: bool = True, redo: list[str] | None = None):
    """The whole setup: the table on the screen, then every box on it.  Returns the config,
    or None when cancelled.  ``redo`` (step keys) marks only those boxes again on the table
    as it was set up.  ``grab_screen()`` gives (screenshot, monitor dict) and
    ``grab_table(region)`` a grab of the table (defaults: the real screen); ``ask_pot()`` and
    ``ask_marker()`` replace the two questions (for tests)."""
    from .capture import grab_once

    if grab_screen is None:
        def grab_screen():
            with screen_grabber() as sct:
                mon = sct.monitors[cfg.monitor if cfg.monitor < len(sct.monitors) else 1]
                shot = sct.grab(mon)
                return Image.frombytes("RGB", shot.size, shot.rgb), mon
    if grab_table is None:
        def grab_table(region):
            return grab_once(region, cfg.monitor)

    with _Root(master) as root:
        root.update()
        time.sleep(0.3)                               # let the caller's window go before the screenshot
        old = Layout.load(layout_path) if (redo and os.path.exists(layout_path) and cfg.region) else None
        if old is None:
            redo = None
            full, mon = grab_screen()
            w1 = BoxWizard(full, [Step("table", "Drag a box around the whole poker table window, then press "
                                                "Enter. Keep the table at this size and place while you play.")],
                           "Coach setup: the table", grab=lambda: grab_screen()[0], master=root)
            first = w1.run()
            if not first:
                return None
            t = first["table"]
            sx, sy = w1.image.width / mon["width"], w1.image.height / mon["height"]
            region = Rect(int(mon["left"] + t.left / sx), int(mon["top"] + t.top / sy),
                          int(t.width / sx), int(t.height / sy))
            root.update()
            time.sleep(0.3)
        else:
            region = Rect(*cfg.region)
            seats = max(seats, len(old.seats))
        table = grab_table(region)
        if old is not None and list(table.size) != list(old.size):
            raise ValueError(f"the table is {table.size[0]}x{table.size[1]} now but was {old.size[0]}x{old.size[1]} "
                             "at setup: put it back to that size, or run the whole setup again")
        steps = table_steps(seats)
        if redo:
            steps = [st for st in steps if st.key in set(redo)]
            if not steps:
                raise ValueError("nothing to mark again: " + ", ".join(redo))
        w2 = BoxWizard(table, steps, "Coach setup: the boxes", grab=lambda: grab_table(region), master=root,
                       shown=layout_boxes(old) if old is not None else None)
        boxes = w2.run()
        if boxes is None:
            return None
        if old is None:
            words = _ask_marker(cfg, root, ask_marker)
            if words is None:
                return None
            lay = layout_from(boxes, w2.images, table.size, seats,
                              _ask_pot(root, ask_pot) if boxes.get("pot") else True, words)
        else:
            lay = apply_boxes(old, boxes, w2.images, seats)
            if "marker" in boxes:
                words = _ask_marker(cfg, root, ask_marker)
                if words is None:
                    return None
                lay.marker_text = words
            if "pot" in boxes:
                lay.pot_includes_bets = _ask_pot(root, ask_pot)
        lay.save(layout_path)
        cfg.region = region.as_list()
        cfg.reader, cfg.seats = "local", len(lay.seats)
        if boxes.get("buttons"):
            cfg.buttons = boxes["buttons"].as_list()
            cfg.baseline = thumb(w2.images["buttons"].crop(boxes["buttons"].box()))
            cfg.baselines = None
        elif old is None:
            cfg.buttons = cfg.baseline = cfg.baselines = None
        cfg.save()
        if teach:
            book = Book.load(book_path)
            shots = list({id(im): im for im in list(w2.images.values()) + [w2.image]}.values())
            items = []
            for k, im in enumerate(shots):
                items += teach_items(im, lay, book, everything=(k == 0 and old is None))
            teach_window(_dedupe(items), book, book_path, master=root, confirm=old is None)
    return cfg


# --------------------------------------------------------------------------
# Teaching
# --------------------------------------------------------------------------

def teach_window(items: list[TeachItem], book: Book, book_path: str, master=None, confirm: bool = False) -> int:
    """Ask what each box shows; returns how many were learned.  Saves the book.

    A box that an earlier answer has made readable is passed over, unless
    ``confirm``: then every box is shown with what the reader makes of it, to
    check (the setup does this once)."""
    if not items:
        return 0
    with _Root(master) as root:
        return _teach(items, book, book_path, root, confirm)


def _zoom(img: Image.Image, width: int = 480, height: int = 160) -> Image.Image:
    z = max(1, min(8, int(width / max(1, img.width)), int(height / max(1, img.height))))
    return img.resize((img.width * z, img.height * z), Image.NEAREST)


def _refresh(item: TeachItem, book: Book) -> None:
    """What the book makes of a text box now (earlier answers may have taught its characters)."""
    if item.kind == "text" and item.pieces:
        item.labels = [book.glyphs.classify(g)[0] for g in item.pieces]
        item.guess = "".join(item.labels)
    elif item.kind == "card":
        item.guess = book.cards.classify(item.image)[0] or ""


def _teach(items, book, book_path, root, confirm: bool = False) -> int:
    import tkinter as tk
    from PIL import ImageTk

    win = tk.Toplevel(root)
    win.focus_force()
    win.title("Coach: teach the reader")
    win.attributes("-topmost", True)
    head = tk.Label(win, font=("Helvetica", 13, "bold"), anchor="w", justify="left", wraplength=520)
    head.pack(fill="x", padx=12, pady=(10, 2))
    hint = tk.Label(win, font=("Helvetica", 10), fg="#4A4A52", anchor="w", justify="left", wraplength=520)
    hint.pack(fill="x", padx=12)
    pic = tk.Label(win)
    pic.pack(padx=12, pady=8)
    entry = tk.Entry(win, font=("Helvetica", 16), width=22)
    entry.pack(padx=12)
    msg = tk.Label(win, font=("Helvetica", 10), fg="#C0392B", anchor="w", justify="left", wraplength=520)
    msg.pack(fill="x", padx=12, pady=(4, 10))
    state = {"i": -1, "learned": 0, "photo": None, "piece": None, "labels": []}

    def picture(img: Image.Image) -> None:
        state["photo"] = ImageTk.PhotoImage(_zoom(img))
        pic.config(image=state["photo"])

    def show() -> None:
        it = items[state["i"]]
        state["piece"] = None
        head.config(text=f"{state['i'] + 1}/{len(items)}  What does this show? ({it.name})")
        if it.kind == "card":
            hint.config(text="Type the card: rank then suit, like Ah, Td, 9c (s h d c). Enter saves, Esc skips.")
        else:
            hint.config(text="Type exactly what it shows, commas and letters included (12,450 · Pot: 1,250 · "
                             "All-in · Sitting Out). Enter saves, Esc skips.")
        picture(it.image)
        entry.delete(0, "end")
        entry.insert(0, it.guess.replace(UNKNOWN, ""))
        entry.focus_set()
        msg.config(text="")

    def show_piece() -> None:
        it, k = items[state["i"]], state["piece"]
        head.config(text=f"{state['i'] + 1}/{len(items)}  {it.name}: piece {k + 1} of {len(it.pieces)}")
        hint.config(text="The box does not cut into one piece per character (an icon in the box, or characters "
                         "that touch). What is this piece? Type the character, or several if they touch. "
                         "Leave it empty and press Enter if it is not a character (an icon, a line).")
        picture(it.pieces[k].point(lambda v: 255 - v))
        entry.delete(0, "end")
        entry.insert(0, "" if it.labels[k] == UNKNOWN else it.labels[k])
        entry.focus_set()
        msg.config(text="")

    def advance() -> None:
        while True:
            state["i"] += 1
            if state["i"] >= len(items):
                book.save(book_path)
                win.destroy()
                return
            it = items[state["i"]]
            _refresh(it, book)
            known = bool(it.guess) and UNKNOWN not in it.guess
            if confirm or not known:
                show()
                return

    def save(_e=None) -> None:
        it = items[state["i"]]
        if state["piece"] is not None:                # labelling the pieces one by one
            state["labels"].append(entry.get().strip())
            if len(state["labels"]) < len(it.pieces):
                state["piece"] += 1
                show_piece()
                return
            why = learn_pieces(book, it, state["labels"])
            state["learned"] += not why
            advance()
            return
        why = learn(book, it, entry.get())
        if why == PIECES and it.pieces:
            state["piece"], state["labels"] = 0, []
            show_piece()
            return
        if why and why != "skipped":
            msg.config(text=why)
            return
        state["learned"] += not why
        advance()

    def skip(_e=None) -> None:
        advance()

    def stop() -> None:
        book.save(book_path)
        win.destroy()

    bar = tk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(0, 10))
    tk.Button(bar, text="Save (Enter)", command=save).pack(side="left")
    tk.Button(bar, text="Skip (Esc)", command=skip).pack(side="left", padx=6)
    tk.Button(bar, text="Stop", command=stop).pack(side="right")
    win.bind("<Return>", save)
    win.bind("<KP_Enter>", save)
    win.bind("<Escape>", skip)
    win.protocol("WM_DELETE_WINDOW", stop)
    advance()
    if win.winfo_exists():
        win.wait_window()
    return state["learned"]


def _dedupe(items: list[TeachItem]) -> list[TeachItem]:
    """One question per distinct picture (the same stack in two screenshots asks once)."""
    seen, out = set(), []
    for it in items:
        key = (it.kind, it.image.tobytes())
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def teach_console(items: list[TeachItem], book: Book, book_path: str, picture_path: str) -> int:
    """The same questions in the terminal: each box is saved as a picture to look at."""
    learned = 0
    for i, it in enumerate(items, 1):
        _refresh(it, book)
        if it.guess and UNKNOWN not in it.guess:
            continue
        _zoom(it.image).save(picture_path)
        kind = "a card like Ah or Td" if it.kind == "card" else "exactly what it shows, e.g. 12,450"
        while True:
            ans = input(f"[{i}/{len(items)}] {it.name}: open {picture_path} and type {kind} "
                        f"(Enter = skip){' [reads ' + it.guess + ']' if it.guess else ''}: ")
            why = learn(book, it, ans)
            if why == PIECES and it.pieces:
                labels = []
                for k, piece in enumerate(it.pieces):
                    _zoom(piece.point(lambda v: 255 - v)).save(picture_path)
                    labels.append(input(f"   piece {k + 1} of {len(it.pieces)} (look at {picture_path}): the "
                                        "character(s), or Enter if it is not a character: ").strip())
                why = learn_pieces(book, it, labels)
            if not why:
                learned += 1
            if not why or why == "skipped":
                break
            print(f"  {why}")
    book.save(book_path)
    try:
        os.remove(picture_path)
    except OSError:
        pass
    return learned


def items_from_images(paths: list[str], layout: Layout, book: Book, limit: int = 40) -> list[TeachItem]:
    """Unknown boxes in saved screenshots (the session log keeps them), newest first."""
    out: list[TeachItem] = []
    for p in sorted(paths, reverse=True):
        try:
            img = Image.open(p).convert("RGB")
        except OSError:
            continue
        if list(img.size) != list(layout.size):
            continue
        out.extend(teach_items(img, layout, book))
        if len(_dedupe(out)) >= limit:
            break
    return _dedupe(out)[:limit]


# --------------------------------------------------------------------------
# Check: what does it read right now?
# --------------------------------------------------------------------------

def check_text(cfg, image: Image.Image, reader=None) -> str:
    """The reading of a table grab and what the coach would say, as text to check by eye."""
    from . import app
    from .decide import HandMemory, suggest
    from .reader import ReadError

    try:
        reader = reader or app.make_reader(cfg)
        result = reader.read(image)
    except ReadError as exc:
        return f"could not read: {exc}"
    sug = suggest(result.table, cfg.settings(), HandMemory(), force=True, blocking=result.blocking)
    return (f"read in {result.seconds * 1000:.0f} ms\n{app.describe_reading(result.table)}\n\n"
            f"{sug.text()}")


# --------------------------------------------------------------------------
# The launcher
# --------------------------------------------------------------------------

def launcher() -> int:
    """One window: Set up · Teach · Check · Start (the packaged program opens this)."""
    import glob
    import tkinter as tk
    from tkinter import messagebox

    from . import app
    from .capture import grab_once

    dpi_aware()
    root = tk.Tk()
    root.title("Poker coach · play money")
    root.resizable(False, False)
    cfg = app.LiveConfig.load()
    tk.Label(root, text="Poker coach", font=("Helvetica", 18, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
    tk.Label(root, text="Reads a play-money table on this computer and suggests the action. It never clicks.",
             font=("Helvetica", 10), fg="#4A4A52").pack(anchor="w", padx=14)
    form = tk.Frame(root)
    form.pack(fill="x", padx=14, pady=8)
    tk.Label(form, text="Seats at the table").grid(row=0, column=0, sticky="w")
    seats = tk.Spinbox(form, from_=2, to=10, width=4)
    seats.delete(0, "end")
    seats.insert(0, str(cfg.seats))
    seats.grid(row=0, column=1, sticky="w", padx=6)
    tk.Label(form, text="Advice").grid(row=1, column=0, sticky="w", pady=(6, 0))
    mode = tk.StringVar(value=cfg.mode)
    modes = tk.Frame(form)
    modes.grid(row=1, column=1, sticky="w", pady=(6, 0))
    for value, label in (("tag", "Tight-aggressive"), ("binary", "All-in or fold"), ("spin", "Spins (3 players)")):
        tk.Radiobutton(modes, text=label, variable=mode, value=value).pack(side="left")
    tk.Label(form, text="Opponents").grid(row=2, column=0, sticky="w", pady=(6, 0))
    opp = tk.StringVar(value=cfg.opponents if cfg.opponents in ("unknown", "loose", "tight") else "unknown")
    opps = tk.Frame(form)
    opps.grid(row=2, column=1, sticky="w", pady=(6, 0))
    for value, label in (("unknown", "Unknown"), ("loose", "Call too much (most play-money tables)"),
                         ("tight", "Tight")):
        tk.Radiobutton(opps, text=label, variable=opp, value=value).pack(side="left")
    status = tk.Label(root, font=("Helvetica", 10), justify="left", anchor="w", wraplength=560)
    status.pack(fill="x", padx=14)

    def ready() -> bool:
        if os.path.exists(app.LAYOUT_PATH) and cfg.region:
            return True
        messagebox.showinfo("Coach", "Set up the table first (step 1).")
        return False

    def refresh() -> None:
        lines = []
        if os.path.exists(app.LAYOUT_PATH):
            lay = Layout.load(app.LAYOUT_PATH)
            miss = lay.problems()
            lines.append(f"Table set up: {len(lay.seats)} seats" + (f" (missing: {', '.join(miss)})" if miss else ""))
            lines += [f"Note: {a}" for a in lay.advice()]
            if not cfg.buttons:
                lines.append("Note: the action buttons are not marked, so it cannot tell when it is your turn")
        else:
            lines.append("Table not set up yet: start with step 1.")
        lines.append(Book.load(app.BOOK_PATH).summary())
        status.config(text="\n".join(lines))

    def keep() -> None:
        cfg.mode, cfg.opponents = mode.get(), opp.get()
        try:
            cfg.seats = max(2, min(10, int(seats.get())))
        except ValueError:
            pass
        cfg.reader = "local"
        cfg.save()

    def grab_table():
        return hidden_grab(root, lambda: grab_once(Rect(*cfg.region), cfg.monitor))

    def do_setup(redo=None) -> None:
        keep()
        root.withdraw()
        try:
            setup_local(cfg, app.LAYOUT_PATH, app.BOOK_PATH, cfg.seats, master=root, redo=redo)
        except Exception as exc:                      # screen access refused, the table changed size...
            messagebox.showerror("Coach", f"Setup failed: {exc}")
        root.deiconify()
        refresh()

    def do_redo() -> None:
        if not ready():
            return
        lay = Layout.load(app.LAYOUT_PATH)
        steps = table_steps(len(lay.seats))
        top = tk.Toplevel(root)
        top.title("Mark some boxes again")
        tk.Label(top, text="Choose the boxes to mark again (Ctrl or Shift for several):").pack(padx=10, pady=(10, 4))
        box = tk.Listbox(top, selectmode="extended", width=44, height=min(22, len(steps)))
        for st in steps:
            box.insert("end", step_label(st.key))
        box.pack(padx=10)
        chosen: list[str] = []

        def ok() -> None:
            chosen.extend(steps[i].key for i in box.curselection())
            top.destroy()

        tk.Button(top, text="Mark these again", command=ok).pack(pady=8)
        root.wait_window(top)
        if chosen:
            do_setup(chosen)

    def do_teach_now() -> None:
        if not ready():
            return
        lay, book = Layout.load(app.LAYOUT_PATH), Book.load(app.BOOK_PATH)
        items = teach_items(grab_table(), lay, book)
        if not items:
            messagebox.showinfo("Coach", "Everything on the table now is already learned.")
        else:
            teach_window(items, book, app.BOOK_PATH, master=root)
        refresh()

    def do_teach_log() -> None:
        if not ready():
            return
        sessions = sorted(glob.glob(os.path.join(app.LOG_ROOT, "*")))
        if not sessions:
            messagebox.showinfo("Coach", "No session yet: start one, then teach from it.")
            return
        lay, book = Layout.load(app.LAYOUT_PATH), Book.load(app.BOOK_PATH)
        items = items_from_images(glob.glob(os.path.join(sessions[-1], "*.png")), lay, book)
        if not items:
            messagebox.showinfo("Coach", "The last session had nothing left to learn.")
        else:
            teach_window(items, book, app.BOOK_PATH, master=root)
        refresh()

    def do_check() -> None:
        if not ready():
            return
        keep()
        try:
            text = check_text(cfg, grab_table())
        except Exception as exc:
            text = f"could not read: {exc}"
        top = tk.Toplevel(root)
        top.title("What the coach reads right now")
        body = tk.Text(top, width=96, height=22, font=("Courier", 10))
        body.insert("1.0", text + "\n\nCompare with the table: your cards, each stack and bet, the D, the pot. "
                                  "A wrong number or card: Teach. A box in the wrong place: mark it again.")
        body.config(state="disabled")
        body.pack(padx=8, pady=8)

    def do_start() -> None:
        keep()
        if not ready():
            return
        import queue
        out = queue.Queue()
        worker = app.Worker(cfg, out)
        worker.start()
        root.withdraw()
        app.run_window(cfg, worker, out, master=root)
        worker.stopped.set()
        root.deiconify()
        refresh()

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=14, pady=12)
    rows = (("1 · Set up the table", do_setup, "Mark some boxes again", do_redo),
            ("2 · Teach from the screen now", do_teach_now, "Teach from the last session", do_teach_log),
            ("3 · Check what it reads now", do_check, "4 · Start", do_start))
    for r, (a, fa, b, fb) in enumerate(rows):
        tk.Button(buttons, text=a, width=30, command=fa).grid(row=r, column=0, pady=2, sticky="w")
        tk.Button(buttons, text=b, width=30, command=fb).grid(row=r, column=1, padx=6)
    tk.Label(root, text="Play money only: it gives no advice unless the table shows your play-money marker.\n"
                        "Keep the coach's windows off the poker table: what covers the table cannot be read.",
             font=("Helvetica", 9), fg="#4A4A52", justify="left").pack(anchor="w", padx=14, pady=(0, 10))
    refresh()
    root.mainloop()
    return 0
