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
# Difference under which a character, a rank or a suit shape counts as recognised.  The
# same character drawn again matches at about 0, or up to about 0.15 when the client
# draws it a fraction of a pixel to the side; the closest different digits (0 and 8)
# differ by about 0.3.  Strict on purpose: an unsure character is asked about, never
# guessed, and every answer is kept as another example.
GLYPH_MATCH = 0.17          # see shape_distance: relative difference, 0 = the same shape
RANK_MATCH = 0.17
SUIT_MATCH = 0.20
GLYPH_GAP = 0.07            # the next-best different label must be this much worse
EXACT = 0.06                # under this the shapes are the same thing drawn again
CUT = 110                   # ink strength (0-255) from which a pixel belongs to a character
MAX_EXAMPLES = 24           # kept per character / rank / suit


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
# Shapes: soft-edged, compared with a little give
# --------------------------------------------------------------------------

def soft(img: Image.Image) -> Image.Image:
    """Ink strength, 0 to 255, keeping the grey edges (``ink`` makes them black or white).

    A client may draw the same digit a fraction of a pixel to the side from one
    time to the next; the grey edge pixels then change a little, where a hard
    black-and-white mask would flip."""
    gray = img.convert("L")
    lo, hi = gray.getextrema()
    if hi - lo < 70:
        return Image.new("L", gray.size, 0)
    t = otsu(gray)
    hist = gray.histogram()[:256]
    n_lo, n_hi = sum(hist[:t + 1]), sum(hist[t + 1:])
    if n_hi <= n_lo:                                 # light ink on a dark ground
        bg = sum(i * h for i, h in enumerate(hist[:t + 1])) / max(1, n_lo)
        fg = float(hi)
    else:
        bg = sum(i * h for i, h in enumerate(hist[t + 1:], t + 1)) / max(1, n_hi)
        fg = float(lo)
    span = (fg - bg) or 1.0
    return gray.point([max(0, min(255, int(round(255.0 * (v - bg) / span)))) for v in range(256)])


def _hard(s: Image.Image) -> Image.Image:
    return s.point(lambda v: 255 if v >= CUT else 0)


def _strip_edges(mask: Image.Image, depth: int = 3) -> Image.Image:
    """Blank lines of ink along the sides of a box (a card's outline, a panel's border)."""
    w, h = mask.size
    if w < 8 or h < 8:
        return mask
    out = mask.copy()
    cols, rows = column_profile(mask), row_profile(mask)
    for k in list(range(depth)) + list(range(w - depth, w)):
        if cols[k] >= 0.6 * 255:
            out.paste(0, (k, 0, k + 1, h))
    for k in list(range(depth)) + list(range(h - depth, h)):
        if rows[k] >= 0.6 * 255:
            out.paste(0, (0, k, w, k + 1))
    return out


def _tight(s: Image.Image, mask: Image.Image, box: tuple) -> tuple[Image.Image, tuple] | tuple[None, None]:
    """The soft shape inside ``box``, cut to its ink with a one-pixel margin."""
    b = mask.crop(box).getbbox()
    if not b:
        return None, None
    x0, y0 = max(box[0], box[0] + b[0] - 1), max(box[1], box[1] + b[1] - 1)
    x1, y1 = min(box[2], box[0] + b[2] + 1), min(box[3], box[1] + b[3] + 1)
    return s.crop((x0, y0, x1, y1)), (x0, y0, x1, y1)


class Shape:
    """A soft shape with what comparing needs worked out once."""
    __slots__ = ("img", "ink", "_pads", "_big")

    def __init__(self, img: Image.Image):
        self.img = img if img.mode == "L" else img.convert("L")
        self.ink = ImageStat.Stat(self.img).sum[0]
        self._pads: dict = {}
        self._big: dict = {}

    def pads(self, w: int, h: int) -> list[Image.Image]:
        """The shape on a (w, h) canvas at the nine places from (0, 0) to (2, 2)."""
        if (w, h) not in self._pads:
            out = []
            for dy in (0, 1, 2):
                for dx in (0, 1, 2):
                    c = Image.new("L", (w, h), 0)
                    c.paste(self.img, (dx, dy))
                    out.append(c)
            self._pads[(w, h)] = out
        return self._pads[(w, h)]

    def big(self, w: int, h: int, up: int) -> Image.Image:
        """Three times larger, in the middle place of a (w, h) canvas."""
        if (w, h) not in self._big:
            self._big[(w, h)] = self.pads(w, h)[4].resize((w * up, h * up), Image.BICUBIC)
        return self._big[(w, h)]

    def large(self, up: int) -> Image.Image:
        if "x" not in self._big:
            self._big["x"] = self.img.resize((self.img.width * up, self.img.height * up), Image.BICUBIC)
        return self._big["x"]


def _coarse(a: Shape, b: Shape) -> tuple[float, int]:
    """(difference, place of b) with b slid by whole pixels."""
    w, h = max(a.img.width, b.img.width) + 2, max(a.img.height, b.img.height) + 2
    base = a.pads(w, h)[4]
    scale = max(1.0, (a.ink + b.ink) / 2.0)
    best, where = 9.0, 4
    for k, c in enumerate(b.pads(w, h)):
        d = ImageStat.Stat(ImageChops.difference(base, c)).sum[0] / scale
        if d < best:
            best, where = d, k
    return best, where


def _fine(a: Shape, b: Shape, where: int, best: float) -> float:
    """The same with b slid by thirds of a pixel around its best whole-pixel place."""
    up = 3
    w, h = max(a.img.width, b.img.width) + 2, max(a.img.height, b.img.height) + 2
    big = a.big(w, h, up)
    bb = b.large(up)
    scale = max(1.0, (ImageStat.Stat(big).sum[0] + ImageStat.Stat(bb).sum[0]) / 2.0)
    bx, by = where % 3, where // 3
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            x, y = bx * up + dx, by * up + dy
            if (dx or dy) and x >= 0 and y >= 0:
                c = Image.new("L", big.size, 0)
                c.paste(bb, (x, y))
                d = ImageStat.Stat(ImageChops.difference(big, c)).sum[0] / scale
                if d < best:
                    best = d
    return best


def shape_distance(a, b, fine: bool = True) -> float:
    """How different two soft shapes are: 0 the same, about 0.3 to 0.6 for different
    digits, 2 for nothing in common.  The difference is measured against the amount of
    ink, so it means the same for small and big print.  The shapes are slid over each
    other by up to a pixel, and with ``fine`` by thirds of a pixel."""
    a = a if isinstance(a, Shape) else Shape(a)
    b = b if isinstance(b, Shape) else Shape(b)
    if abs(a.img.width - b.img.width) > 2 or abs(a.img.height - b.img.height) > 2:
        return 2.0
    d, where = _coarse(a, b)
    return d if d <= EXACT or not fine else _fine(a, b, where, d)


_SAME = {",": "sep", ".": "sep", "'": "sep"}       # confusing these changes no amount


def nearest(shape: Image.Image, examples: dict, limit: float, gap: float) -> tuple[str | None, float]:
    """(label, difference) of the closest example, or (None, difference) when nothing is
    close enough or two different labels are about equally close.  ``examples`` is
    {label: [Shape]}."""
    a = Shape(shape)
    rough = []
    for label, shapes in examples.items():
        for ex in shapes:
            if abs(a.img.width - ex.img.width) > 2 or abs(a.img.height - ex.img.height) > 2:
                continue
            # the difference is at least the difference in ink: skip what cannot matter
            if abs(a.ink - ex.ink) / max(1.0, (a.ink + ex.ink) / 2.0) > limit + gap + 0.1:
                continue
            d, where = _coarse(a, ex)
            rough.append((d, label, ex, where))
    if not rough:
        return None, 2.0
    rough.sort(key=lambda r: r[0])
    per: dict[str, float] = {}
    for d, label, _, _ in rough:
        per.setdefault(label, d)
    if rough[0][0] > EXACT:                          # look closer at the best few
        seen: dict[str, int] = {}
        for d, label, ex, where in rough[:10]:
            if seen.get(label, 0) >= 2 or (len(seen) >= 3 and label not in seen):
                continue
            seen[label] = seen.get(label, 0) + 1
            per[label] = min(per[label], _fine(a, ex, where, d))
    order = sorted((d, label) for label, d in per.items())
    d0, label = order[0]
    if d0 > limit:
        return None, d0
    kind = _SAME.get(label, label)
    for d, other in order[1:]:
        if d >= d0 + gap:
            break
        if _SAME.get(other, other) != kind:
            return None, d0
    return label, d0


# --------------------------------------------------------------------------
# Text: cut into characters, match, parse
# --------------------------------------------------------------------------

def _column_max(s: Image.Image, x: int) -> int:
    return s.crop((x, 0, x + 1, s.height)).getextrema()[1]


def _split_wide(band: Image.Image, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Cut pieces that are too wide for one character at their thinnest column: characters
    in bold print can touch."""
    limit = max(6, int(0.95 * band.height))
    out = []
    todo = list(spans)
    while todo:
        x0, x1 = todo.pop(0)
        if x1 - x0 <= limit:
            out.append((x0, x1))
            continue
        inner = [(x, _column_max(band, x)) for x in range(x0 + 3, x1 - 3)]
        if not inner:
            out.append((x0, x1))
            continue
        x, level = min(inner, key=lambda c: (c[1], abs(c[0] - (x0 + x1) / 2.0)))
        if level > 190:                              # solid all the way: one wide character
            out.append((x0, x1))
            continue
        todo = [(x0, x), (x + 1, x1)] + todo
    return sorted(out)


def glyphs(img: Image.Image) -> list[Image.Image]:
    """The characters of a line of text, left to right, as soft shapes cut to their ink."""
    s = soft(img)
    mask = _hard(s)
    box = mask.getbbox()
    if not box:
        return []
    band = mask.crop((0, box[1], mask.width, box[3]))
    spans = _split_wide(s.crop((0, box[1], s.width, box[3])), runs(column_profile(band)))
    out = []
    for k, (x0, x1) in enumerate(spans):
        left = max(x0 - 1, spans[k - 1][1] if k else 0)
        right = min(x1 + 1, spans[k + 1][0] if k + 1 < len(spans) else s.width)
        g, _ = _tight(s, mask, (left, max(0, box[1] - 1), right, min(s.height, box[3] + 1)))
        if g is None:
            g, _ = _tight(s, mask, (x0, box[1], x1, box[3]))
        if g is not None:
            out.append(g)
    return out


@dataclass
class GlyphBook:
    """Learned pieces of text: {label: [examples as base64 PNG]}.

    A label is usually one character.  It can be several (characters that
    touch and cannot be cut apart) or empty (a piece that is not text, such
    as a chip icon inside a bet box: it reads as nothing)."""
    chars: dict[str, list[str]] = field(default_factory=dict)
    _cache: dict = field(default_factory=dict, repr=False)
    _memo: dict = field(default_factory=dict, repr=False)

    def images(self, ch: str) -> list[Shape]:
        key = (ch, len(self.chars.get(ch, [])), (self.chars.get(ch) or [""])[-1][-24:])
        if key not in self._cache:
            self._cache[key] = [Shape(from_b64(x)) for x in self.chars.get(ch, [])]
        return self._cache[key]

    def classify(self, g: Image.Image) -> tuple[str, float]:
        """(label, difference); the label is '?' when the piece is not known for sure."""
        key = (g.size, g.tobytes())
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        label, d = nearest(g, {ch: self.images(ch) for ch in self.chars}, GLYPH_MATCH, GLYPH_GAP)
        if label is None:
            return UNKNOWN, d
        if len(self._memo) > 20000:
            self._memo.clear()
        self._memo[key] = (label, d)
        return label, d

    def read(self, img: Image.Image) -> str:
        """The text in an image ('?' for pieces not learned yet; '' when blank)."""
        return "".join(self.classify(g)[0] for g in glyphs(img))

    def add(self, g: Image.Image, label: str) -> None:
        known, d = self.classify(g)
        if known == label and d <= EXACT:            # already known exactly
            return
        self.chars.setdefault(label, []).append(png_b64(g))
        self.chars[label] = self.chars[label][-MAX_EXAMPLES:]
        self._memo.clear()

    def learn(self, img: Image.Image, text: str) -> bool:
        """Learn the characters of ``text`` (spaces ignored) from an image showing it.
        False when the image does not cut into that many pieces: label them one by one
        with ``learn_pieces``."""
        chars = [c for c in text if not c.isspace()]
        gs = glyphs(img)
        if not chars or len(gs) != len(chars):
            return False
        for c, g in zip(chars, gs):
            self.add(g, c)
        return True

    def learn_pieces(self, img: Image.Image, labels: list[str]) -> bool:
        """One label per piece, left to right: a character, several, or '' for not text."""
        gs = glyphs(img)
        if len(gs) != len(labels):
            return False
        for label, g in zip(labels, gs):
            self.add(g, "".join(label.split()))
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


def has_ink(img: Image.Image) -> bool:
    """Something is drawn here (strong contrast), whatever it is."""
    return _hard(soft(img)).getbbox() is not None


def split_corner(img: Image.Image) -> tuple[Image.Image | None, Image.Image | None, tuple | None]:
    """(rank shape, suit shape, suit box in the image) of a card corner.  The rank is
    above the suit; if they stand side by side, the rank is on the left."""
    s = soft(img)
    mask = _strip_edges(_hard(s))
    box = mask.getbbox()
    if not box:
        return None, None, None
    bands = runs(row_profile(mask))
    if len(bands) > 1:
        rank, _ = _tight(s, mask, (0, bands[0][0], mask.width, bands[0][1]))
        suit, sbox = _tight(s, mask, (0, bands[1][0], mask.width, bands[-1][1]))
        return rank, suit, sbox
    cols = runs(column_profile(mask))
    if len(cols) > 1:
        rank, _ = _tight(s, mask, (cols[0][0], 0, cols[-2][1], mask.height))
        suit, sbox = _tight(s, mask, (cols[-1][0], 0, cols[-1][1], mask.height))
        return rank, suit, sbox
    rank, _ = _tight(s, mask, (0, 0, mask.width, mask.height))
    return rank, None, None


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
    """Learned card corners: rank shapes by rank, suit shapes and colours by suit."""
    ranks: dict[str, list[str]] = field(default_factory=dict)
    suits: dict[str, list[dict]] = field(default_factory=dict)       # [{"colour", "mask"}]
    _cache: dict = field(default_factory=dict, repr=False)
    _memo: dict = field(default_factory=dict, repr=False)

    def _imgs(self, key: tuple, items: list[str]) -> list[Shape]:
        k = key + (len(items), (items or [""])[-1][-24:])
        if k not in self._cache:
            self._cache[k] = [Shape(from_b64(x)) for x in items if x]
        return self._cache[k]

    def classify(self, img: Image.Image) -> tuple[str | None, str]:
        """(card like 'Ah' or None, what went wrong)."""
        key = (img.size, img.tobytes())
        if key in self._memo:
            return self._memo[key], ""
        rank_shape, suit_shape, sbox = split_corner(img)
        if rank_shape is None:
            return None, "no rank found"
        rank, _ = nearest(rank_shape, {r: self._imgs(("r", r), items) for r, items in self.ranks.items()},
                          RANK_MATCH, GLYPH_GAP)
        if rank is None:
            return None, "rank not learned yet"
        colour = ink_colour(img, sbox)
        same_colour = {s for s, exs in self.suits.items() if any(e["colour"] == colour for e in exs)}
        if len(same_colour) == 1:
            suit = same_colour.pop()
        else:
            if suit_shape is None:
                return None, "suit not found"
            shapes = {s: self._imgs(("s", s), [e.get("mask", "") for e in exs]) for s, exs in self.suits.items()
                      if not same_colour or s in same_colour}
            suit, _ = nearest(suit_shape, shapes, SUIT_MATCH, GLYPH_GAP)
            if suit is None:
                return None, "suit not learned yet"
        if len(self._memo) > 5000:
            self._memo.clear()
        self._memo[key] = rank + suit
        return rank + suit, ""

    def learn(self, img: Image.Image, card: str) -> bool:
        card = card.strip()
        if len(card) == 3 and card[:2] == "10":
            card = "T" + card[2]
        if len(card) != 2 or card[0].upper() not in RANKS or card[1].lower() not in SUITS:
            return False
        r, s = card[0].upper(), card[1].lower()
        rank_shape, suit_shape, sbox = split_corner(img)
        if rank_shape is None:
            return False
        self.ranks.setdefault(r, []).append(png_b64(rank_shape))
        self.ranks[r] = self.ranks[r][-MAX_EXAMPLES:]
        entry = {"colour": ink_colour(img, sbox), "mask": png_b64(suit_shape) if suit_shape is not None else ""}
        self.suits.setdefault(s, []).append(entry)
        self.suits[s] = self.suits[s][-MAX_EXAMPLES:]
        self._memo.clear()
        return True


# --------------------------------------------------------------------------
# The book on disk
# --------------------------------------------------------------------------

BOOK_VERSION = 2            # 1 kept hard black-and-white shapes; they are not comparable


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
        if d.get("version") != BOOK_VERSION:
            return cls()
        return cls(GlyphBook(d.get("chars", {})), CardBook(d.get("ranks", {}), d.get("suits", {})))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"version": BOOK_VERSION, "chars": self.glyphs.chars, "ranks": self.cards.ranks,
                       "suits": self.cards.suits}, fh)

    def summary(self) -> str:
        chars = "".join(sorted(c for c in self.glyphs.chars if len(c) == 1))
        extra = sorted(c for c in self.glyphs.chars if len(c) > 1)
        ranks = "".join(r for r in RANKS if r in self.cards.ranks)
        suits = "".join(s for s in SUITS if s in self.cards.suits)
        missing = "".join(r for r in RANKS if r not in self.cards.ranks)
        return (f"characters learned: {chars or 'none'}" + (f" (+ {' '.join(extra)})" if extra else "")
                + f" | ranks: {ranks or 'none'}" + (f" (still to learn: {missing})" if missing else "")
                + f" | suits: {suits or 'none'}")
