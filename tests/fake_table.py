"""Draws a simple six-seat poker table, to test the local reader without a poker client.

``render(spec)`` returns the image and the layout of every box, as the setup
wizard would record it.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 640
SUIT_COLOURS = {"s": (20, 20, 20), "h": (200, 30, 30), "d": (30, 70, 210), "c": (20, 140, 40)}


def _font(size: int, bold: bool = False):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


SMALL, RANK, BIG = _font(16, True), _font(20, True), _font(18, True)


def _seat_centre(k: int) -> tuple[int, int]:
    """Seat 0 (hero) at the bottom, then clockwise."""
    a = math.radians(90 + 60 * k)
    return int(W / 2 + 390 * math.cos(a)), int(H / 2 - 20 + 235 * math.sin(a))


def _suit(draw, x, y, s, size=14):
    col = SUIT_COLOURS[s]
    if s == "h":
        draw.ellipse((x, y, x + size, y + size), fill=col)
    elif s == "d":
        draw.polygon([(x + size / 2, y), (x + size, y + size / 2), (x + size / 2, y + size), (x, y + size / 2)], fill=col)
    elif s == "s":
        draw.polygon([(x + size / 2, y), (x + size, y + size), (x, y + size)], fill=col)
    else:
        r = size / 3
        for cx, cy in ((x + size / 2, y + r), (x + r, y + size - r), (x + size - r, y + size - r)):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)


def _card(draw, x, y, card):
    draw.rectangle((x, y, x + 46, y + 64), fill=(250, 250, 250), outline=(120, 120, 120))
    rank, suit = card[0], card[1]
    text = "10" if rank == "T" else rank
    draw.text((x + 4, y + 2), text, font=RANK, fill=SUIT_COLOURS[suit])
    _suit(draw, x + 6, y + 28, suit)


def _centred(draw, cx, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text((int(cx - w / 2), y), text, font=font, fill=fill)


def render(spec: dict) -> tuple[Image.Image, dict]:
    """spec: seats [{stack, bet, cards(bool), word}], button (seat index), hero [2 cards],
    board [cards], pot (number), turn (bool), marker (bool)."""
    img = Image.new("RGB", (W, H), (25, 60, 45))
    d = ImageDraw.Draw(img)
    d.ellipse((120, 90, W - 120, H - 130), fill=(30, 110, 60), outline=(90, 60, 30), width=12)
    boxes = {"seats": [], "hero_cards": [], "board": []}
    if spec.get("marker", True):
        d.text((14, 10), "PLAY MONEY", font=SMALL, fill=(255, 214, 10))
    boxes["marker"] = [10, 6, 120, 26]
    for k in range(6):
        cx, cy = _seat_centre(k)
        seat = spec["seats"][k] if k < len(spec["seats"]) else None
        sb = [cx - 60, cy + 18, 120, 26]
        dx, dy = (W / 2 - cx) * 0.35, (H / 2 - 20 - cy) * 0.35
        bet_box = [int(cx + dx - 60), int(cy + dy - 12), 120, 24]
        n = math.hypot(dx, dy) or 1.0
        px, py = -dy / n * 85, dx / n * 85                 # beside the line from the seat to the centre
        btn_box = [int(cx + dx * 0.5 + px - 20), int(cy + dy * 0.5 + py - 20), 40, 40]
        cards_box = [cx - 40, cy - 40, 80, 56]
        boxes["seats"].append({"stack": sb, "bet": bet_box, "button": btn_box, "cards": cards_box if k else None})
        if seat is None:
            continue
        d.rectangle((sb[0], sb[1], sb[0] + sb[2], sb[1] + sb[3]), fill=(15, 15, 18))
        text = seat.get("word") or f"{seat['stack']:,.0f}"
        _centred(d, cx, sb[1] + 4, text, SMALL, (240, 240, 240))
        if seat.get("bet"):
            _centred(d, bet_box[0] + 60, bet_box[1] + 3, f"{seat['bet']:,.0f}", SMALL, (255, 214, 10))
        if k and seat.get("cards", True):
            for j in range(2):
                x = cx - 34 + j * 30
                d.rectangle((x, cy - 34, x + 36, cy + 10), fill=(160, 20, 30), outline=(255, 255, 255), width=2)
                d.line((x + 4, cy - 30, x + 32, cy + 6), fill=(230, 120, 120), width=2)
    b = spec.get("button")
    if b is not None:
        bx = boxes["seats"][b]["button"]
        d.ellipse((bx[0] + 8, bx[1] + 8, bx[0] + 32, bx[1] + 32), fill=(245, 245, 245), outline=(40, 40, 40), width=2)
        d.text((bx[0] + 14, bx[1] + 10), "D", font=SMALL, fill=(20, 20, 20))
    hx, hy = _seat_centre(0)
    for j in range(2):
        x, y = hx - 50 + j * 54, hy - 49
        boxes["hero_cards"].append([x + 1, y + 1, 30, 50])
        if spec.get("hero"):
            _card(d, x, y, spec["hero"][j])
    for j in range(5):
        x, y = W // 2 - 140 + j * 56, H // 2 - 50
        boxes["board"].append([x + 1, y + 1, 30, 50])
        if j < len(spec.get("board", [])):
            _card(d, x, y, spec["board"][j])
    boxes["pot"] = [W // 2 - 90, H // 2 - 92, 180, 26]
    if spec.get("pot") is not None:
        _centred(d, W // 2, H // 2 - 88, f"Pot: {spec['pot']:,.0f}", SMALL, (240, 240, 240))
    boxes["buttons"] = [W - 330, H - 70, 320, 60]
    if spec.get("turn", True):
        for j, label in enumerate(("Fold", "Call", "Raise")):
            x = W - 330 + j * 108
            d.rectangle((x, H - 66, x + 100, H - 16), fill=(180, 40, 40))
            _centred(d, x + 50, H - 52, label, SMALL, (255, 255, 255))
    return img, boxes


def layout_for(img: Image.Image, boxes: dict, marker_text: str = "PLAY MONEY"):
    """The layout the setup wizard would save for this fake table (``img`` must show the
    button at seat 0)."""
    from poker_coach.live.capture import Rect
    from poker_coach.live.local import Layout, SeatLayout
    from poker_coach.live.vision import png_b64

    lay = Layout(size=list(img.size), hero_cards=boxes["hero_cards"], board=boxes["board"], pot=boxes["pot"],
                 pot_includes_bets=True, marker=boxes["marker"], marker_text=marker_text,
                 seats=[SeatLayout(**s) for s in boxes["seats"]])
    lay.marker_template = png_b64(img.crop(Rect(*boxes["marker"]).box()))
    b = boxes["seats"][0]["button"]
    lay.button_template = png_b64(img.crop((b[0] + 6, b[1] + 6, b[0] + 34, b[1] + 34)))
    c = boxes["seats"][1]["cards"]
    lay.backs_template = png_b64(img.crop((c[0] + 5, c[1] + 5, c[0] + 72, c[1] + 51)))
    return lay


def truth(spec: dict, name: str) -> str:
    """What a teaching question about this box should be answered with."""
    if name.startswith("your card"):
        return spec["hero"][int(name[-1]) - 1]
    if name.startswith("board card"):
        return spec["board"][int(name[-1]) - 1]
    if name == "the pot":
        return f"Pot: {spec['pot']:,}"
    k = 0 if name.startswith("your") else int(name.split()[1]) - 1
    return f"{spec['seats'][k]['stack' if 'stack' in name else 'bet']:,}"
