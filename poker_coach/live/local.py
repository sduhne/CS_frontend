"""The local reader: a screenshot of the table -> a ``TableRead``, with no network.

It needs two files made on the user's computer:

* ``layout.json`` (made by the setup wizard): where each thing is on the
  table, in pixels of the table grab, plus a few templates (the dealer
  button, a pair of face-down cards, the play-money marker);
* ``book.json`` (made by teaching): the client's characters and card
  corners, learned from boxes the user labelled.

It never guesses.  What it cannot read for sure it reports: things a decision
depends on (your cards, the board, any bet, your stack) go to ``blocking``
and stop the advice until they are taught; ``teach_items`` lists those boxes
so the user can label them once.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field

from PIL import Image

from .capture import Rect, difference, thumb
from .reader import ReadError, ReadResult
from .schema import SeatRead, TableRead
from .vision import (Book, UNKNOWN, best_match, blank_score, card_present, found, from_b64, glyphs, has_ink,
                     parse_amount, word_of)

BUTTON_MATCH = 55.0          # sliding-template difference under which the dealer button is there
BACKS_MATCH = 55.0           # ... and a pair of face-down cards
MARKER_MATCH = 40.0          # ... and the play-money marker (fixed place)
TURN_CHANGE = 12.0           # action-button area: difference from its idle look that means "your turn"


def _box(r) -> tuple[int, int, int, int]:
    return Rect(*r).box()


@dataclass
class SeatLayout:
    stack: list[int] | None = None           # boxes are [left, top, width, height] in table-grab pixels
    bet: list[int] | None = None
    button: list[int] | None = None          # where the dealer button sits when this seat has it
    cards: list[int] | None = None           # where this player's face-down cards show (not for you)


@dataclass
class Layout:
    size: list[int] = field(default_factory=lambda: [0, 0])
    hero_cards: list[list[int]] = field(default_factory=list)
    board: list[list[int]] = field(default_factory=list)
    pot: list[int] | None = None
    pot_includes_bets: bool = True
    players_left: list[int] | None = None
    marker: list[int] | None = None
    marker_template: str = ""
    marker_text: str = ""                    # what the marker says (it must be a play-money word)
    button_template: str = ""
    backs_template: str = ""
    seats: list[SeatLayout] = field(default_factory=list)     # clockwise, seat 1 is you

    @classmethod
    def load(cls, path: str) -> "Layout":
        with open(path) as fh:
            d = json.load(fh)
        d["seats"] = [SeatLayout(**s) for s in d.get("seats", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump(asdict(self), fh)

    def problems(self) -> list[str]:
        """What is missing for a reading to work."""
        out = []
        if len(self.hero_cards) != 2 or not all(self.hero_cards):
            out.append("your two card corners")
        if len(self.seats) < 2:
            out.append("at least two seats")
        if not self.button_template:
            out.append("the dealer button")
        if not self.marker or not self.marker_template or not self.marker_text:
            out.append("the play-money marker")
        for k, s in enumerate(self.seats, 1):
            if not s.stack:
                out.append(f"seat {k} stack")
            if not s.bet:
                out.append(f"seat {k} bet")
            if not s.button:
                out.append(f"seat {k} button place")
        return out

    def advice(self) -> list[str]:
        """Things that work but will give worse advice, or look like a slip in the setup."""
        out = []
        if len(self.board) < 5:
            out.append(f"only {len(self.board)} of the 5 board cards are marked: no advice after the flop "
                       "for the missing ones")
        if not self.pot:
            out.append("the pot is not marked: no advice after the flop")
        if not self.backs_template or any(not s.cards for s in self.seats[1:]):
            out.append("face-down cards are not marked for every opponent: it cannot see who has folded")
        if not self.clockwise():
            out.append("the seats do not go clockwise from you (seat 2 must be the player on your left): "
                       "positions would be wrong, so set the seats up again")
        return out

    def clockwise(self) -> bool:
        """The seats' stack boxes go round the table clockwise, as seen on the screen."""
        pts = [(s.stack[0] + s.stack[2] / 2.0, s.stack[1] + s.stack[3] / 2.0) for s in self.seats if s.stack]
        if len(pts) < 3:
            return True
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        # on a screen y grows downwards, so clockwise means the angle grows
        angles = [math.atan2(y - cy, x - cx) for x, y in pts]
        turn = 0.0
        for a, b in zip(angles, angles[1:] + angles[:1]):
            step = (b - a) % (2 * math.pi)
            if step > math.pi * 1.5:                 # a step backwards
                return False
            turn += step
        return abs(turn - 2 * math.pi) < 0.01


@dataclass
class TeachItem:
    kind: str                    # "text" or "card"
    name: str                    # what the box is, for the person labelling it
    image: Image.Image
    guess: str = ""
    pieces: list = field(default_factory=list)       # text: the pieces it cuts into
    labels: list = field(default_factory=list)       # and what each reads as ('?' when unknown)


def signature(t: TableRead) -> tuple:
    """What a decision depends on: two readings with the same signature show the same spot."""
    return (tuple(t.hero_cards), tuple(t.board), t.hero_to_act, t.total_pot, t.middle_pot, t.money_text,
            tuple((s.stack, s.bet, s.folded, s.all_in, s.has_button, s.sitting_out) for s in t.seats),
            t.unreadable)


class LocalReader:
    """Reads the table with the learned book; remembers the blinds between hands."""

    def __init__(self, layout: Layout, book: Book, buttons: list[int] | None = None,
                 baseline=None):
        self.layout, self.book = layout, book
        self.buttons = buttons
        # one idle look of the action-button area, or several
        self.baselines = [baseline] if baseline and isinstance(baseline[0], int) else list(baseline or [])
        self.sb: float | None = None
        self.bb: float | None = None
        self.ante: float = 0.0
        self.ante_kind = "none"
        self._hand: tuple | None = None              # (button seat, your cards): changes with each hand
        self._hand_blinds: tuple | None = None       # the smallest blinds seen in this hand
        self._hand_antes: float | None = None
        self._last_stack: dict[int, float] = {}
        self._templates = {k: from_b64(getattr(layout, k)) if getattr(layout, k) else None
                           for k in ("marker_template", "button_template", "backs_template")}
        self._blank = {k: blank_score(t) for k, t in self._templates.items() if t is not None}

    # -- pieces ---------------------------------------------------------
    def crop(self, image: Image.Image, r) -> Image.Image:
        return image.crop(_box(r))

    def text(self, image: Image.Image, r) -> str:
        return self.book.glyphs.read(self.crop(image, r)) if r else ""

    def card(self, image: Image.Image, r) -> tuple[str | None, bool]:
        """(card, present): a present card that cannot be named yet gives (None, True)."""
        crop = self.crop(image, r)
        light = card_present(crop)
        if not light and not has_ink(crop):
            return None, False
        name, _why = self.book.cards.classify(crop)
        if name:
            return name, True
        return None, light                           # a dark slot that is no known card: nothing there

    def marker_seen(self, image: Image.Image) -> bool:
        tpl = self._templates["marker_template"]
        if not tpl or not self.layout.marker:
            return False
        return found(self.crop(image, self.layout.marker), tpl, MARKER_MATCH, self._blank["marker_template"])

    def turn_look(self, image: Image.Image) -> list[int] | None:
        return thumb(image.crop(Rect(*self.buttons).box())) if self.buttons else None

    def hero_turn(self, image: Image.Image) -> bool:
        if not self.buttons or not self.baselines:
            return True
        look = self.turn_look(image)
        return min(difference(look, b) for b in self.baselines) > TURN_CHANGE

    # -- the reading ----------------------------------------------------
    def read(self, image: Image.Image) -> ReadResult:
        start = time.time()
        lay = self.layout
        if lay.size and list(image.size) != list(lay.size):
            raise ReadError(f"the table grab is {image.size[0]}x{image.size[1]} but was "
                            f"{lay.size[0]}x{lay.size[1]} at setup: keep the table window the same size, or set up again")
        blocking: list[str] = []                     # stops the advice
        notes: list[str] = []                        # worth knowing

        hero_cards = []
        for k, r in enumerate(lay.hero_cards):
            c, present = self.card(image, r)
            if present and c is None:
                blocking.append(f"your card {k + 1} is not learned yet")
            elif c:
                hero_cards.append(c)
        if len(hero_cards) != 2:
            hero_cards = []
        board = []
        for k, r in enumerate(lay.board):
            c, present = self.card(image, r)
            if not present:
                break
            if c is None:
                blocking.append(f"board card {k + 1} is not learned yet")
                break
            board.append(c)
        if len(board) in (1, 2) and not blocking:
            blocking.append("the board is still being dealt")
        seen = hero_cards + board
        if len(set(seen)) != len(seen):
            twice = sorted({c for c in seen if seen.count(c) > 1})
            blocking.append(f"the same card was read twice ({' '.join(twice)}): teach the cards again with "
                            "live-teach --all")

        seats: list[SeatRead] = []
        btn_scores = []
        backs = self._templates["backs_template"]
        btn_tpl = self._templates["button_template"]
        for k, s in enumerate(lay.seats):
            who = "your" if k == 0 else f"seat {k + 1}"
            raw = self.text(image, s.stack)
            if raw == "":
                continue                             # empty seat
            word = word_of(raw)
            stack = None if word else parse_amount(raw)
            if stack is None and not word:
                if UNKNOWN in raw:
                    (blocking if k == 0 else notes).append(f"{who} stack is not learned yet")
                else:                                # learned text that is no number: a label over the stack
                    stack = self._last_stack.get(k)
            elif stack is not None:
                self._last_stack[k] = stack
            bet = 0.0
            braw = self.text(image, s.bet)
            if braw:
                v = parse_amount(braw)
                if v is not None:
                    bet = v
                elif UNKNOWN in braw:
                    blocking.append(f"{who} bet is not learned yet")
            if k == 0:
                in_hand = bool(hero_cards) or any(card_present(self.crop(image, r)) for r in lay.hero_cards)
            elif backs is not None and s.cards:
                in_hand = found(self.crop(image, s.cards), backs, BACKS_MATCH, self._blank["backs_template"])
            else:
                in_hand = True
            if btn_tpl is not None and s.button:
                btn_scores.append((best_match(self.crop(image, s.button), btn_tpl), len(seats)))
            all_in = word == "all-in" or (stack == 0 and bet > 0)
            seats.append(SeatRead(name=f"Seat {k + 1}" if k else "You", stack=0.0 if all_in else stack,
                                  bet=float(bet), is_hero=(k == 0), has_button=False, folded=not in_hand,
                                  all_in=all_in, sitting_out=(word == "away")))
        if btn_scores:
            score, idx = min(btn_scores)
            if score <= BUTTON_MATCH and score <= 0.5 * self._blank["button_template"]:
                seats[idx] = seats[idx].model_copy(update={"has_button": True})
            else:
                notes.append("dealer button not found")
        if not seats or not seats[0].is_hero:
            notes.append("your seat shows no stack")

        pot_val = None
        if lay.pot:
            praw = self.text(image, lay.pot)
            pot_val = parse_amount(praw) if praw else None
            if praw and pot_val is None and UNKNOWN in praw:
                (blocking if board else notes).append("the pot is not learned yet")
        left = None
        if lay.players_left:
            lraw = self.text(image, lay.players_left)
            v = parse_amount(lraw) if lraw else None
            left = int(v) if v else None

        bets_ok = not any("bet is not learned" in b for b in blocking)
        self._learn_blinds(seats, hero_cards, board, pot_val, bets_ok)
        middle = total = None
        if pot_val is not None:
            if lay.pot_includes_bets:
                total = pot_val
            else:
                middle = pot_val
        table = TableRead(
            is_poker_table=True,
            money_text=lay.marker_text if self.marker_seen(image) else
                       "(marker from setup not found: has the table moved?)",
            table_text="", hero_to_act=self.hero_turn(image), hero_cards=hero_cards, board=board,
            small_blind=self.sb, big_blind=self.bb, ante=self.ante or None, ante_kind=self.ante_kind,
            amounts_in_bb=False, middle_pot=middle, total_pot=total, players_left=left, places_paid=None,
            entrants=None, average_stack=None, seats=seats, unreadable="; ".join(blocking + notes))
        return ReadResult(table, time.time() - start, 0, 0, 0.0, "local reader", blocking)

    def observe(self, image: Image.Image) -> ReadResult | None:
        """A quiet reading between turns: keeps the blinds and the ante up to date."""
        try:
            return self.read(image)
        except ReadError:
            return None

    def _learn_blinds(self, seats: list[SeatRead], hero_cards: list[str], board: list[str],
                      pot: float | None, bets_ok: bool) -> None:
        """Before the flop the two seats after the button have the blinds in front.

        Later in the hand those two can hold a raise and a re-raise that look like
        blinds, so within a hand the smallest pair seen counts, and a pair is not
        taken while somebody has fewer chips in front than its big blind."""
        btn = next((k for k, s in enumerate(seats) if s.has_button), None)
        hand = (seats[btn].name if btn is not None else "", tuple(hero_cards))
        if hand != self._hand:
            self._hand, self._hand_blinds, self._hand_antes = hand, None, None
        n = len(seats)
        if board or not bets_ok or btn is None or n < 2:
            return
        sb_k, bb_k = (btn, (btn + 1) % n) if n == 2 else ((btn + 1) % n, (btn + 2) % n)
        sb, bb = seats[sb_k].bet, seats[bb_k].bet
        short = [k for k, s in enumerate(seats) if k not in (sb_k, bb_k) and 0 < s.bet < bb and not s.all_in]
        cand = None
        if sb > 0 and bb > 0 and 0.3 <= sb / bb <= 0.7 and not seats[bb_k].all_in and not short:
            cand = (sb, bb)
        elif bb > 0 and self.bb is None and not seats[bb_k].all_in \
                and all(s.bet == 0 or s.bet >= bb for k, s in enumerate(seats) if k != sb_k):
            # never seen the blinds and the small blind has called, raised or is missing: the
            # big blind's own chips are the big blind as long as nobody has fewer in front
            cand = (sb if 0 < sb < bb else bb / 2.0, bb)
        if cand and self.bb and self._hand_blinds is None and cand[1] > 3.0 * self.bb:
            cand = None                              # blinds do not triple between hands: a raise and a re-raise
        if cand and (self._hand_blinds is None or cand[1] < self._hand_blinds[1]):
            self._hand_blinds = cand
            self.sb, self.bb = cand
        if pot is None or not self.bb:
            return
        antes = pot - sum(s.bet for s in seats) if self.layout.pot_includes_bets else pot
        if antes < -0.01 * self.bb or (self._hand_antes is not None and antes <= self._hand_antes):
            return
        if antes <= 0.05 * self.bb:
            ante, kind = 0.0, "none"
        elif abs(antes - self.bb) <= 0.15 * self.bb:
            ante, kind = antes, "big_blind"
        elif antes / n <= 0.35 * self.bb:
            ante, kind = antes / n, "per_player"
        else:
            return                                   # not an ante: something was misread
        self._hand_antes = antes
        self.ante, self.ante_kind = ante, kind


# --------------------------------------------------------------------------
# What to teach
# --------------------------------------------------------------------------

def teach_items(image: Image.Image, layout: Layout, book: Book, everything: bool = False) -> list[TeachItem]:
    """Boxes in this screenshot that the book cannot read yet (all non-blank ones with
    ``everything``)."""
    out: list[TeachItem] = []

    def text_box(name, r):
        if not r:
            return
        crop = image.crop(_box(r))
        pieces = glyphs(crop)
        if not pieces:
            return
        labels = [book.glyphs.classify(g)[0] for g in pieces]
        if everything or UNKNOWN in labels:
            out.append(TeachItem("text", name, crop, "".join(labels), pieces, labels))

    def card_box(name, r):
        if not r:
            return
        crop = image.crop(_box(r))
        guess, _ = book.cards.classify(crop) if has_ink(crop) else (None, "")
        if card_present(crop) and (everything or guess is None):
            out.append(TeachItem("card", name, crop, guess or ""))
        elif everything and has_ink(crop):           # a deck with dark or coloured faces
            out.append(TeachItem("card", name + " (if a card is showing)", crop, guess or ""))

    for k, r in enumerate(layout.hero_cards):
        card_box(f"your card {k + 1}", r)
    for k, r in enumerate(layout.board):
        card_box(f"board card {k + 1}", r)
    for k, s in enumerate(layout.seats, 1):
        who = "your" if k == 1 else f"seat {k}"
        text_box(f"{who} stack", s.stack)
        text_box(f"{who} bet", s.bet)
    text_box("the pot", layout.pot)
    text_box("players left", layout.players_left)
    return out


PIECES = "pieces"            # learn() answers this when the text must be labelled piece by piece


def learn(book: Book, item: TeachItem, answer: str) -> str:
    """Store a label; returns '' when learned, 'skipped', ``PIECES`` when the typed text
    does not have one character per piece (label the pieces with ``learn_pieces``), or
    what is wrong with the answer."""
    answer = answer.strip()
    if not answer:
        return "skipped"
    if item.kind == "card":
        return "" if book.cards.learn(item.image, answer) else "type a card like Ah, Td or 10c"
    if book.glyphs.learn(item.image, answer):
        return ""
    return PIECES


def learn_pieces(book: Book, item: TeachItem, labels: list[str]) -> str:
    """One label per piece of a text box ('' for a piece that is not a character)."""
    return "" if book.glyphs.learn_pieces(item.image, labels) else "the pieces do not match the box"
