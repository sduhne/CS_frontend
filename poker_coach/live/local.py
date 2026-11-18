"""The local reader: a screenshot of the table -> a ``TableRead``, with no network.

It needs two files made on the user's computer:

* ``layout.json`` (made by the setup wizard): where each thing is on the
  table, in pixels of the table grab, plus a few templates (the dealer
  button, a pair of face-down cards, the play-money marker);
* ``book.json`` (made by teaching): the client's characters and card
  corners, learned from boxes the user labelled.

What it cannot read it reports, and ``teach_items`` lists those boxes so the
user can label them once.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field

from PIL import Image

from .capture import Rect, difference, thumb
from .reader import ReadError, ReadResult
from .schema import SeatRead, TableRead
from .vision import Book, UNKNOWN, best_match, blank_score, card_present, found, from_b64, parse_amount, word_of

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
        if len(self.hero_cards) != 2:
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


@dataclass
class TeachItem:
    kind: str                    # "text" or "card"
    name: str                    # what the box is, for the person labelling it
    image: Image.Image
    guess: str = ""


class LocalReader:
    """Reads the table with the learned book; remembers the blinds between hands."""

    def __init__(self, layout: Layout, book: Book, buttons: list[int] | None = None,
                 baseline: list[int] | None = None):
        self.layout, self.book = layout, book
        self.buttons, self.baseline = buttons, baseline
        self.sb: float | None = None
        self.bb: float | None = None
        self.ante: float = 0.0
        self.ante_kind = "none"
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
        if not card_present(crop):
            return None, False
        name, _why = self.book.cards.classify(crop)
        return name, True

    def marker_seen(self, image: Image.Image) -> bool:
        tpl = self._templates["marker_template"]
        if not tpl or not self.layout.marker:
            return False
        return found(self.crop(image, self.layout.marker), tpl, MARKER_MATCH, self._blank["marker_template"])

    def hero_turn(self, image: Image.Image) -> bool:
        if not self.buttons or not self.baseline:
            return True
        return difference(thumb(image.crop(Rect(*self.buttons).box())), self.baseline) > TURN_CHANGE

    # -- the reading ----------------------------------------------------
    def read(self, image: Image.Image) -> ReadResult:
        start = time.time()
        lay = self.layout
        if lay.size and list(image.size) != list(lay.size):
            raise ReadError(f"the table grab is {image.size[0]}x{image.size[1]} but was "
                            f"{lay.size[0]}x{lay.size[1]} at setup: keep the table window the same size, or set up again")
        notes: list[str] = []
        hero_cards = []
        for k, r in enumerate(lay.hero_cards):
            c, present = self.card(image, r)
            if present and c is None:
                notes.append(f"your card {k + 1} not learned yet")
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
                notes.append(f"board card {k + 1} not learned yet")
                board = []
                break
            board.append(c)

        seats: list[SeatRead] = []
        number_of: dict[int, int] = {}            # layout seat index -> index in ``seats``
        btn_scores = []
        backs = self._templates["backs_template"]
        btn_tpl = self._templates["button_template"]
        for k, s in enumerate(lay.seats):
            raw = self.text(image, s.stack)
            if raw == "":
                continue                           # empty seat
            word = word_of(raw)
            stack = parse_amount(raw) if not word else None
            if UNKNOWN in raw and not word:
                notes.append(f"seat {k + 1} stack not learned yet")
            braw = self.text(image, s.bet)
            bet = parse_amount(braw) if braw else 0.0
            if braw and bet is None:
                notes.append(f"seat {k + 1} bet not learned yet")
                bet = 0.0
            if k == 0:
                in_hand = bool(hero_cards) or any(card_present(self.crop(image, r)) for r in lay.hero_cards)
            elif backs is not None and s.cards:
                in_hand = found(self.crop(image, s.cards), backs, BACKS_MATCH, self._blank["backs_template"])
            else:
                in_hand = True
            if btn_tpl is not None and s.button:
                btn_scores.append((best_match(self.crop(image, s.button), btn_tpl), len(seats)))
            number_of[k] = len(seats)
            seats.append(SeatRead(name=f"Seat {k + 1}" if k else "You", stack=0.0 if word == "all-in" else stack,
                                  bet=float(bet or 0.0), is_hero=(k == 0), has_button=False,
                                  folded=not in_hand, all_in=(word == "all-in"), sitting_out=(word == "away")))
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
            if praw and pot_val is None:
                notes.append("pot not learned yet")
        left = None
        if lay.players_left:
            lraw = self.text(image, lay.players_left)
            v = parse_amount(lraw) if lraw else None
            left = int(v) if v else None

        if not board:
            self._learn_blinds(seats, pot_val)
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
            entrants=None, average_stack=None, seats=seats, unreadable="; ".join(notes))
        return ReadResult(table, time.time() - start, 0, 0, 0.0, "local reader")

    def observe(self, image: Image.Image) -> None:
        """A quiet reading between turns: keeps the blinds and the ante up to date."""
        try:
            self.read(image)
        except ReadError:
            pass

    def _learn_blinds(self, seats: list[SeatRead], pot: float | None) -> None:
        """Before the flop the two seats after the button have the blinds in front."""
        live = [k for k, s in enumerate(seats) if not s.sitting_out]
        btn = next((k for k, s in enumerate(seats) if s.has_button), None)
        if btn is None or len(live) < 2:
            return
        after = [k for k in live if k > btn] + [k for k in live if k <= btn]
        sb_k, bb_k = (btn, after[0]) if len(live) == 2 else (after[0], after[1])
        sb, bb = seats[sb_k].bet, seats[bb_k].bet
        if bb > 0 and sb > 0 and 0.3 <= sb / bb <= 0.7 and not seats[bb_k].all_in:
            self.sb, self.bb = sb, bb
        elif bb > 0 and self.bb is None:
            self.sb, self.bb = bb / 2.0, bb
        if pot is None or not self.bb:
            return
        bets = sum(s.bet for s in seats)
        antes = pot - bets if self.layout.pot_includes_bets else pot
        if antes <= 0.05 * self.bb:
            self.ante, self.ante_kind = 0.0, "none"
        elif abs(antes - self.bb) <= 0.15 * self.bb and len(live) > 2:
            self.ante, self.ante_kind = antes, "big_blind"
        else:
            self.ante, self.ante_kind = antes / len(live), "per_player"


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
        guess = book.glyphs.read(crop)
        if guess and (everything or UNKNOWN in guess):
            out.append(TeachItem("text", name, crop, guess))

    def card_box(name, r):
        crop = image.crop(_box(r))
        if not card_present(crop):
            return
        guess, _ = book.cards.classify(crop)
        if everything or guess is None:
            out.append(TeachItem("card", name, crop, guess or ""))

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


def learn(book: Book, item: TeachItem, answer: str) -> str:
    """Store a label; returns '' when learned, else why not."""
    answer = answer.strip()
    if not answer:
        return "skipped"
    if item.kind == "card":
        return "" if book.cards.learn(item.image, answer) else "type a card like Ah, Td or 10c"
    if book.glyphs.learn(item.image, answer):
        return ""
    from .vision import glyphs
    n = len(glyphs(item.image))
    return (f"the box shows {n} separate characters but you typed {len([c for c in answer if not c.isspace()])}: "
            "type exactly what it shows, including commas and letters")
