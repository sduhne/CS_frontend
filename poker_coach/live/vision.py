"""Local image recognition for a poker client: no network, no model.

A poker client draws the same pixels for the same thing every time, so the
reader does not need to understand images: it compares them with examples
the user has labelled once.

* Text (stacks, bets, pot) is cut into characters at the empty columns
  between them; each character is matched with the learned examples.
* A card corner is cut into the rank (top) and the suit (below); the rank is
  matched with learned ranks, the suit by its colour (four-colour decks) or by
  its shape.
* Fixed things (the dealer button, card backs, the play-money marker) are
  found by sliding a template over the area where they can appear.

Only Pillow is needed.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageStat

UNKNOWN = "?"
# Mean pixel difference (0-255) under which a character, a rank or a suit shape counts as
# recognised.  The same character drawn again matches at about 0; the closest different
# digits (0 and 8) differ by about 30.  Strict on purpose: an unsure character is asked
# about, never guessed, and every answer is kept as another example.
GLYPH_MATCH = 20.0
RANK_MATCH = 20.0
SUIT_MATCH = 25.0
MAX_EXAMPLES = 12           # kept per character / rank / suit


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def png_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def from_b64(text: str) -> Image.Image:
    img = Image.open(io.BytesIO(base64.standard_b64decode(text)))
    img.load()
    return img


def otsu(gray: Image.Image) -> int:
    """The grey level that best splits the image into two groups."""
    hist = gray.histogram()[:256]
    total = sum(hist)
    if not total:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    w0 = s0 = 0.0
    best, thr = -1.0, 128
    for t in range(256):
        w0 += hist[t]
        if w0 == 0:
            continue
        w1 = total - w0
        if w1 == 0:
            break
        s0 += t * hist[t]
        m0, m1 = s0 / w0, (sum_all - s0) / w1
        between = w0 * w1 * (m0 - m1) ** 2
        if between > best:
            best, thr = between, t
    return thr


def ink(img: Image.Image) -> Image.Image:
    """Black-and-white mask (ink = 255): the smaller of the two groups is the ink."""
    gray = img.convert("L")
    lo, hi = gray.getextrema()
    if hi - lo < 70:                                # no strong contrast: nothing written (felt, edges)
        return Image.new("L", gray.size, 0)
    t = otsu(gray)
    bright = gray.point(lambda v: 255 if v > t else 0)
    share = ImageStat.Stat(bright).mean[0] / 255.0
    return bright if share < 0.5 else ImageChops.invert(bright)


def runs(values: list[float], min_value: float = 0.0) -> list[tuple[int, int]]:
    """Runs of positions whose value is above ``min_value``: [(start, end_exclusive)]."""
    out, start = [], None
    for i, v in enumerate(values):
        if v > min_value and start is None:
            start = i
        elif v <= min_value and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(values)))
    return out


def column_profile(mask: Image.Image) -> list[float]:
    return list(mask.resize((mask.width, 1), Image.BOX).tobytes())


def row_profile(mask: Image.Image) -> list[float]:
    return list(mask.resize((1, mask.height), Image.BOX).tobytes())


def distance(a: Image.Image, b: Image.Image, slack: int = 2) -> float:
    """Mean pixel difference of two masks (0 = the same).  Sizes may differ by ``slack``
    pixels; beyond that they are different things."""
    if abs(a.width - b.width) > slack or abs(a.height - b.height) > slack:
        return 255.0
    w, h = max(a.width, b.width), max(a.height, b.height)
    ca, cb = Image.new("L", (w, h), 0), Image.new("L", (w, h), 0)
    ca.paste(a, (0, 0))
    cb.paste(b, (0, 0))
    return ImageStat.Stat(ImageChops.difference(ca, cb)).mean[0]


def _scan(reg: Image.Image, tpl: Image.Image, xs, ys) -> tuple[float, int, int]:
    best = (255.0, 0, 0)
    for y in ys:
        for x in xs:
            crop = reg.crop((x, y, x + tpl.width, y + tpl.height))
            d = sum(ImageStat.Stat(ImageChops.difference(crop, tpl)).mean) / 3.0
            if d < best[0]:
                best = (d, x, y)
    return best


def blank_score(template: Image.Image) -> float:
    """What an empty patch of the template's background colour would score against it."""
    tpl = template.convert("RGB")
    flat = Image.new("RGB", tpl.size, tuple(int(v) for v in ImageStat.Stat(tpl).median))
    return sum(ImageStat.Stat(ImageChops.difference(flat, tpl)).mean) / 3.0


def found(region: Image.Image, template: Image.Image, limit: float, blank: float | None = None) -> bool:
    """The template is in the region: close in absolute terms and far closer than an empty
    patch would be (a sparse template, such as a word, is mostly background)."""
    blank = blank_score(template) if blank is None else blank
    score = best_match(region, template)
    return score <= limit and score <= 0.5 * blank


def best_match(region: Image.Image, template: Image.Image, step: int = 2) -> float:
    """Smallest mean difference of ``template`` slid over ``region`` (colour images).

    Big search areas are scanned coarsely at half size first, then refined
    around the best place, so a generous box costs a few milliseconds."""
    if template.width > region.width or template.height > region.height:
        return 255.0
    reg, tpl = region.convert("RGB"), template.convert("RGB")
    free_x, free_y = reg.width - tpl.width, reg.height - tpl.height
    places = (free_x + 1) * (free_y + 1)
    if places <= 100:                                          # small area: every position
        return _scan(reg, tpl, range(free_x + 1), range(free_y + 1))[0]
    if places <= 1600 or min(tpl.size) < 12:                   # every other one, then the neighbours
        _, x, y = _scan(reg, tpl, range(0, free_x + 1, step), range(0, free_y + 1, step))
        return _scan(reg, tpl, range(max(0, x - 1), min(free_x, x + 1) + 1),
                     range(max(0, y - 1), min(free_y, y + 1) + 1))[0]
    sreg = reg.resize((reg.width // 2, reg.height // 2), Image.BOX)
    stpl = tpl.resize((tpl.width // 2, tpl.height // 2), Image.BOX)
    sx, sy = sreg.width - stpl.width, sreg.height - stpl.height
    c = 1
    while (sx // c + 1) * (sy // c + 1) > 250:
        c += 1
    _, cx, cy = _scan(sreg, stpl, range(0, sx + 1, c), range(0, sy + 1, c))
    x, y, r = cx * 2, cy * 2, 2 * c
    _, x, y = _scan(reg, tpl, range(max(0, x - r), min(free_x, x + r) + 1, 2),
                    range(max(0, y - r), min(free_y, y + r) + 1, 2))
    return _scan(reg, tpl, range(max(0, x - 1), min(free_x, x + 1) + 1), range(max(0, y - 1), min(free_y, y + 1) + 1))[0]


# --------------------------------------------------------------------------
# Text: cut into characters, match, parse
# --------------------------------------------------------------------------

def glyphs(img: Image.Image) -> list[Image.Image]:
    """The characters of a line of text, left to right, each cut to the line's height."""
    mask = ink(img)
    box = mask.getbbox()
    if not box:
        return []
    line = mask.crop((0, box[1], mask.width, box[3]))
    out = []
    for x0, x1 in runs(column_profile(line)):
        g = line.crop((x0, 0, x1, line.height))
        if g.getbbox():
            out.append(g)
    return out


@dataclass
class GlyphBook:
    """Learned characters: {character: [examples as base64 PNG]}."""
    chars: dict[str, list[str]] = field(default_factory=dict)
    _cache: dict = field(default_factory=dict, repr=False)

    def images(self, ch: str) -> list[Image.Image]:
        key = (ch, len(self.chars.get(ch, [])))
        if key not in self._cache:
            self._cache[key] = [from_b64(x) for x in self.chars.get(ch, [])]
        return self._cache[key]

    def classify(self, g: Image.Image) -> tuple[str, float]:
        best, label = 255.0, UNKNOWN
        for ch in self.chars:
            for ex in self.images(ch):
                d = distance(g, ex)
                if d < best:
                    best, label = d, ch
        return (label if best <= GLYPH_MATCH else UNKNOWN), best

    def read(self, img: Image.Image) -> str:
        """The text in an image ('?' for characters not learned yet; '' when blank)."""
        return "".join(self.classify(g)[0] for g in glyphs(img))

    def learn(self, img: Image.Image, text: str) -> bool:
        """Learn the characters of ``text`` (spaces ignored) from an image showing it."""
        chars = [c for c in text if not c.isspace()]
        gs = glyphs(img)
        if not chars or len(gs) != len(chars):
            return False
        for c, g in zip(chars, gs):
            label, d = self.classify(g)
            if label == c and d < 8:                 # already known exactly
                continue
            self.chars.setdefault(c, []).append(png_b64(g))
            self.chars[c] = self.chars[c][-MAX_EXAMPLES:]
        return True

    def unknown(self, img: Image.Image) -> bool:
        return UNKNOWN in self.read(img)


_NUMBER = re.compile(r"\d[\d,.]*\s*[KkMm]?")


def parse_amount(text: str) -> float | None:
    """'12,345' -> 12345; '1.250' -> 1250; '1.2K' -> 1200; '12.5' -> 12.5; 'Pot: 1,234' -> 1234.
    With a slash ('23/150') the number after it."""
    if not text or UNKNOWN in text:
        return None
    if "/" in text:
        text = text.split("/")[-1]
    m = None
    for m in _NUMBER.finditer(text):
        pass
    if m is None:
        return None
    tok = m.group(0).replace(" ", "")
    mult = 1.0
    if tok[-1] in "Kk":
        mult, tok = 1e3, tok[:-1]
    elif tok[-1] in "Mm":
        mult, tok = 1e6, tok[:-1]
    if "," in tok and "." in tok:
        dec = "." if tok.rfind(".") > tok.rfind(",") else ","
        tok = tok.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in tok:
        parts = tok.split(",")
        tok = tok.replace(",", "") if all(len(p) == 3 for p in parts[1:]) else tok.replace(",", ".")
    elif tok.count(".") > 1 or (mult == 1.0 and "." in tok and len(tok.split(".")[1]) == 3):
        tok = tok.replace(".", "")                   # 1.250 and 12.450.000 are thousands
    try:
        return float(tok.strip(".")) * mult
    except ValueError:
        return None


def word_of(text: str) -> str:
    """'all-in', 'away' or '' for the words a stack box can show instead of a number."""
    t = re.sub(r"[^a-z]", "", (text or "").lower())
    if t.startswith("all") or "allin" in t:
        return "all-in"
    if t.startswith(("sit", "away", "out")):
        return "away"
    return ""


# --------------------------------------------------------------------------
# Cards
# --------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "shdc"


def card_present(img: Image.Image) -> bool:
    """A card face is mostly light; felt, an empty slot or a card back is not."""
    gray = img.convert("L")
    light = gray.point(lambda v: 255 if v >= 170 else 0)
    return ImageStat.Stat(light).mean[0] / 255.0 >= 0.30


def split_corner(img: Image.Image) -> tuple[Image.Image | None, Image.Image | None, tuple | None]:
    """(rank mask, suit mask, suit box in the image) of a card corner: the first band
    of ink from the top is the rank, the next one the suit."""
    mask = ink(img)
    box = mask.getbbox()
    if not box:
        return None, None, None
    bands = runs(row_profile(mask))
    if not bands:
        return None, None, None

    def cut(y0, y1):
        part = mask.crop((0, y0, mask.width, y1))
        b = part.getbbox()
        return (part.crop(b), (b[0], y0 + b[1], b[2], y0 + b[3])) if b else (None, None)

    rank, _ = cut(*bands[0])
    suit, sbox = cut(bands[1][0], bands[-1][1]) if len(bands) > 1 else (None, None)
    return rank, suit, sbox


def ink_colour(img: Image.Image, box: tuple | None = None) -> str:
    """black, red, green or blue: the colour of the ink (a four-colour deck tells the suit)."""
    part = img.crop(box) if box else img
    mask = ink(part)
    if not mask.getbbox():
        return "black"
    r, g, b = ImageStat.Stat(part.convert("RGB"), mask).mean[:3]
    if max(r, g, b) - min(r, g, b) < 45:
        return "black"
    top = max(r, g, b)
    return "red" if top == r else "green" if top == g else "blue"


@dataclass
class CardBook:
    """Learned card corners: rank masks by rank, suit masks and colours by suit."""
    ranks: dict[str, list[str]] = field(default_factory=dict)
    suits: dict[str, list[dict]] = field(default_factory=dict)       # [{"colour", "mask"}]
    _cache: dict = field(default_factory=dict, repr=False)

    def _imgs(self, key: tuple, items: list[str]) -> list[Image.Image]:
        k = key + (len(items),)
        if k not in self._cache:
            self._cache[k] = [from_b64(x) for x in items]
        return self._cache[k]

    def classify(self, img: Image.Image) -> tuple[str | None, str]:
        """(card like 'Ah' or None, what went wrong)."""
        if not card_present(img):
            return None, ""
        rank_mask, suit_mask, sbox = split_corner(img)
        if rank_mask is None:
            return None, "no rank found"
        best, rank = 255.0, None
        for r, items in self.ranks.items():
            for ex in self._imgs(("r", r), items):
                d = distance(rank_mask, ex)
                if d < best:
                    best, rank = d, r
        if rank is None or best > RANK_MATCH:
            return None, "rank not learned yet"
        colour = ink_colour(img, sbox)
        same_colour = {s for s, exs in self.suits.items() if any(e["colour"] == colour for e in exs)}
        if len(same_colour) == 1:
            return rank + same_colour.pop(), ""
        best, suit = 255.0, None
        for s, exs in self.suits.items():
            if same_colour and s not in same_colour:
                continue
            for e in exs:
                if suit_mask is None or not e.get("mask"):
                    continue
                d = distance(suit_mask, from_b64(e["mask"]))
                if d < best:
                    best, suit = d, s
        if suit is None or best > SUIT_MATCH:
            return None, "suit not learned yet"
        return rank + suit, ""

    def learn(self, img: Image.Image, card: str) -> bool:
        card = card.strip()
        if len(card) == 3 and card[:2] == "10":
            card = "T" + card[2]
        if len(card) != 2 or card[0].upper() not in RANKS or card[1].lower() not in SUITS:
            return False
        r, s = card[0].upper(), card[1].lower()
        rank_mask, suit_mask, sbox = split_corner(img)
        if rank_mask is None:
            return False
        self.ranks.setdefault(r, []).append(png_b64(rank_mask))
        self.ranks[r] = self.ranks[r][-MAX_EXAMPLES:]
        entry = {"colour": ink_colour(img, sbox), "mask": png_b64(suit_mask) if suit_mask is not None else ""}
        self.suits.setdefault(s, []).append(entry)
        self.suits[s] = self.suits[s][-MAX_EXAMPLES:]
        return True


# --------------------------------------------------------------------------
# The book on disk
# --------------------------------------------------------------------------

@dataclass
class Book:
    glyphs: GlyphBook = field(default_factory=GlyphBook)
    cards: CardBook = field(default_factory=CardBook)

    @classmethod
    def load(cls, path: str) -> "Book":
        if not os.path.exists(path):
            return cls()
        with open(path) as fh:
            d = json.load(fh)
        return cls(GlyphBook(d.get("chars", {})), CardBook(d.get("ranks", {}), d.get("suits", {})))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"chars": self.glyphs.chars, "ranks": self.cards.ranks, "suits": self.cards.suits}, fh)

    def summary(self) -> str:
        chars = "".join(sorted(self.glyphs.chars))
        ranks = "".join(r for r in RANKS if r in self.cards.ranks)
        suits = "".join(s for s in SUITS if s in self.cards.suits)
        missing = "".join(r for r in RANKS if r not in self.cards.ranks)
        return (f"characters learned: {chars or 'none'} | ranks: {ranks or 'none'}"
                + (f" (still to learn: {missing})" if missing else "") + f" | suits: {suits or 'none'}")
